#!/usr/bin/env python3
"""
Tile‑wise QA_Error extractor for DXF drawings
--------------------------------------------
Exports a CSV with columns:
    Tile_Grid_Name , Error_Description , X_Coordinate , Y_Coordinate
"""

from __future__ import annotations
import sys
import math
from pathlib import Path
from typing import List, Tuple, Sequence, Dict
import ezdxf
import pandas as pd


# ═════════════════════════════════════════════════════════════════════════════
#  Geometry helpers
# ═════════════════════════════════════════════════════════════════════════════
def close_ring(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Ensure first == last (needed for point‑in‑polygon)."""
    return pts if pts[0] == pts[-1] else pts + [pts[0]]


def poly_from_entity(e) -> List[Tuple[float, float]]:
    """
    Return a closed list of (x, y) vertices if *e* looks like a tile boundary.
    Handles: LWPOLYLINE, POLYLINE, HATCH (outer loop), 3DFACE.
    Otherwise returns [].
    """
    pts: List[Tuple[float, float]] = []

    if e.dxftype() == "LWPOLYLINE":
        pts = [(p[0], p[1]) for p in e.get_points()]

    elif e.dxftype() == "POLYLINE":
        pts = [(v.dxf.location.x, v.dxf.location.y) for v in e.vertices]

    elif e.dxftype() == "HATCH" and e.paths:
        pts = [(v[0], v[1]) for v in e.paths[0].vertices]

    elif e.dxftype() == "3DFACE":
        # 3DFACE has up to 4 vertices; vtx3 may duplicate vtx2 or vtx0
        verts = [
            e.dxf.vtx0,
            e.dxf.vtx1,
            e.dxf.vtx2,
            e.dxf.vtx3,
        ]
        # Filter None and collapse duplicates (faces are planar)
        seen = set()
        for v in verts:
            if v is None:
                continue
            xy = (v[0], v[1])
            if xy not in seen:
                pts.append(xy)
                seen.add(xy)

    if len(pts) < 3:               # not enough to form an area
        return []

    pts = close_ring(pts)          # auto‑close open rings
    return pts if len(pts) >= 4 else []


def centroid(poly: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    xs, ys = zip(*poly[:-1])
    return sum(xs) / len(xs), sum(ys) / len(ys)


def point_in_poly(pt: Tuple[float, float],
                  poly: Sequence[Tuple[float, float]]) -> bool:
    """Ray‑casting algorithm for PIP test."""
    x, y = pt
    inside = False
    px, py = poly[0]
    for qx, qy in poly[1:]:
        if (py > y) != (qy > y):
            xinters = (qx - px) * (y - py) / (qy - py) + px
            if x < xinters:
                inside = not inside
        px, py = qx, qy
    return inside


# ═════════════════════════════════════════════════════════════════════════════
#  Core processing
# ═════════════════════════════════════════════════════════════════════════════
def build_polygon_index(
        msp,
        boundary_layers: List[str],
        name_layers: List[str],
) -> Dict[str, List[Tuple[float, float]]]:
    """
    Return {tile_name: polygon}.
    • A polygon gets the single text that lies inside it; if none lie inside
      the nearest text to its centroid is chosen.
    • Duplicate names get suffixed “_2”, “_3”, …
    """
    # 1️⃣  Collect boundary polygons
    polygons: List[List[Tuple[float, float]]] = []
    debug_counter: Dict[str, int] = {}
    for lyr in boundary_layers:
        for ent in msp.query(f'*[layer=="{lyr}"]'):
            poly = poly_from_entity(ent)
            if poly:
                polygons.append(poly)
            debug_counter[ent.dxftype()] = debug_counter.get(ent.dxftype(), 0) + 1

    if not polygons:
        print("\n‼️  No closed boundaries recognised on layer(s)", boundary_layers)
        print("    Entities present on those layers:")
        for k, v in sorted(debug_counter.items()):
            print(f"      {k:<10}: {v}")
        sys.exit(1)

    # 2️⃣  Collect tile‑name texts
    texts = []
    for lyr in name_layers:
        for t in msp.query(f'TEXT MTEXT[layer=="{lyr}"]'):
            raw = t.dxf.text if t.dxftype() == "TEXT" else (t.text or "")
            content = raw.strip()
            if not content:
                continue
            pos = (t.dxf.insert.x, t.dxf.insert.y)
            texts.append({"name": content, "pos": pos})

    if not texts:
        print("‼️  No tile‑name texts found on layer(s):", name_layers)
        sys.exit(1)

    # 3️⃣  Assign a unique name to each polygon
    poly_index: Dict[str, List[Tuple[float, float]]] = {}
    for poly in polygons:
        cx, cy = centroid(poly)
        chosen, best_d2 = None, math.inf
        for t in texts:
            if point_in_poly(t["pos"], poly):
                chosen = t["name"]
                break
            dx, dy = t["pos"][0] - cx, t["pos"][1] - cy
            d2 = dx * dx + dy * dy
            if d2 < best_d2:
                best_d2, chosen = d2, t["name"]

        # guarantee uniqueness
        if chosen in poly_index:
            suffix = 2
            while f"{chosen}_{suffix}" in poly_index:
                suffix += 1
            chosen = f"{chosen}_{suffix}"

        poly_index[chosen] = poly

    return poly_index


def extract_qc_errors(
        msp,
        qa_layer: str,
        poly_index: Dict[str, List[Tuple[float, float]]],
) -> pd.DataFrame:
    """Return DataFrame with required columns."""
    records = []
    for e in msp.query(f'TEXT MTEXT[layer=="{qa_layer}"]'):
        raw = e.dxf.text if e.dxftype() == "TEXT" else (e.text or "")
        txt = raw.strip()
        if not txt:
            continue
        ins = (e.dxf.insert.x, e.dxf.insert.y)

        # containment first
        chosen = next((n for n, P in poly_index.items() if point_in_poly(ins, P)),
                      None)

        # fallback → nearest centroid
        if not chosen:
            best_name, best_d2 = None, math.inf
            for n, P in poly_index.items():
                cx, cy = centroid(P)
                dx, dy = ins[0] - cx, ins[1] - cy
                d2 = dx * dx + dy * dy
                if d2 < best_d2:
                    best_d2, best_name = d2, n
            chosen = best_name or "Unknown"

        records.append(dict(Tile_Grid_Name=chosen,
                            Error_Description=txt,
                            X_Coordinate=ins[0],
                            Y_Coordinate=ins[1]))

    if not records:
        print("‼️  No QA_Error text entities found on layer:", qa_layer)
        sys.exit(1)

    return (pd.DataFrame(records)
            .sort_values(["Tile_Grid_Name", "Error_Description"]))


# ═════════════════════════════════════════════════════════════════════════════
#  Simple CLI helpers
# ═════════════════════════════════════════════════════════════════════════════
def prompt_path(prompt: str, must_exist=True, default_ext=None) -> Path:
    while True:
        p = Path(input(prompt).strip('"').strip())
        if default_ext and p.suffix.lower() != default_ext:
            p = p.with_suffix(default_ext)
        if must_exist and not p.exists():
            print("   ✗  path not found – try again.")
        else:
            return p


def main():
    print("=" * 60)
    print(" Tile‑wise QA_Error extractor")
    print("=" * 60)

    dxf_path = prompt_path("\nDXF file: ", must_exist=True)
    grid_layers = (input("Tile‑grid boundary layer(s) (comma) [TileGrid]: ")
                   .strip() or "TileGrid")
    name_layers = (input("Tile‑name text layer(s) (comma)  [TileGrid_Text]: ")
                   .strip() or "TileGrid_Text")
    qa_layer = input("QA_Error layer [QA_Error]: ").strip() or "QA_Error"
    out_csv = prompt_path("Output CSV path: ", must_exist=False, default_ext=".csv")

    try:
        doc = ezdxf.readfile(dxf_path)
    except Exception as exc:
        print("‼️  Could not read DXF:", exc)
        sys.exit(1)

    msp = doc.modelspace()

    poly_index = build_polygon_index(msp,
                                     [l.strip() for l in grid_layers.split(",")],
                                     [l.strip() for l in name_layers.split(",")])
    print(f"   → indexed {len(poly_index)} tile polygons")

    df = extract_qc_errors(msp, qa_layer, poly_index)
    df.to_csv(out_csv, index=False)

    print(f"\n✅  Saved {len(df)} errors → {out_csv}")
    print("Summary (errors per tile):")
    for tile, grp in df.groupby("Tile_Grid_Name"):
        print(f" • {tile}: {len(grp)}")
    print("\nDone.")


if __name__ == "__main__":
    main()
