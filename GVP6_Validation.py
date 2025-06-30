"""
GIS Polygon–Point Validation Tool
Python ≥3.9 • GeoPandas ≥0.14 • Shapely ≥2.0
───────────────────────────────────────────────────────────────────────────────
Rule
────
For every GVP that
  • has TPC == 6 AND
  • whose point_IDN starts with any user‑supplied prefix AND
  • lies inside a building polygon whose polygon_IDN starts with the same prefix
verify that *either* the previous or next point around that polygon
(immediate clockwise order along the polygon boundary) has TPC == 1.
If neither neighbour is TPC == 1, the point is flagged as an error.
CSV output: Description, IDN, TPC, Polygon_IDN, Previous_TPC, Next_TPC
"""

from __future__ import annotations

import os
import sys
import traceback
from typing import Iterable, Tuple

import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.geometry import (
    Point,
    Polygon,
    MultiPolygon,
    LineString,
    MultiLineString,
)
from shapely.ops import unary_union, nearest_points


# ──────────────────────────────────────────────────────────────
# Small helpers
# ──────────────────────────────────────────────────────────────


def _rename_common(
    left: gpd.GeoDataFrame,
    right: gpd.GeoDataFrame,
    *,
    left_suffix: str = "_pt",
    right_suffix: str = "_poly",
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Avoid name clashes before spatial join."""
    clash = (set(left.columns) & set(right.columns)) - {"geometry"}
    if clash:
        left = left.rename(columns={c: f"{c}{left_suffix}" for c in clash})
        right = right.rename(columns={c: f"{c}{right_suffix}" for c in clash})
    return left, right


def _prefer(df: pd.DataFrame, name: str, aliases: Iterable[str]) -> str:
    """Return *name* if present, else first alias, else raise."""
    if name in df.columns:
        return name
    for alt in aliases:
        if alt in df.columns:
            return alt
    raise KeyError(f"Required column '{name}' not in {list(df.columns)}")


# ──────────────────────────────────────────────────────────────
# Loading functions
# ──────────────────────────────────────────────────────────────


def load_polygons(path: str, prefixes: Tuple[str, ...]) -> gpd.GeoDataFrame:
    """Read building polygons & filter by prefix."""
    gbg = gpd.read_file(path)
    if "IDN" not in gbg:
        raise ValueError("gbg.shp is missing field «IDN»")
    gbg = gbg.rename(columns={"IDN": "polygon_IDN"})
    gbg["polygon_IDN"] = gbg["polygon_IDN"].astype(str)
    gbg = gbg[gbg["polygon_IDN"].str.startswith(prefixes)]
    return gbg


def load_points(path: str) -> gpd.GeoDataFrame:
    """Read GVP points & normalise field names."""
    gvp = gpd.read_file(path)
    for fld in ("IDN", "TPC"):
        if fld not in gvp:
            raise ValueError(f"gvp.shp is missing field «{fld}»")
    gvp = gvp.rename(columns={"IDN": "point_IDN"})
    gvp["point_IDN"] = gvp["point_IDN"].astype(str)
    return gvp


# ──────────────────────────────────────────────────────────────
# Spatial association
# ──────────────────────────────────────────────────────────────


def associate_points(
    pts: gpd.GeoDataFrame,
    polys: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """LEFT‑join points ➟ polygons so each point knows its polygon_IDN."""
    if pts.crs != polys.crs:
        pts = pts.to_crs(polys.crs)

    pts, polys = _rename_common(pts.copy(), polys.copy())
    joined = gpd.sjoin(
        pts,
        polys[["polygon_IDN", "geometry"]],
        how="left",
        predicate="intersects",
    )

    # normalise TPC name
    tpc_col = _prefer(joined, "TPC", aliases=["TPC_pt", "TPC_left"])
    if tpc_col != "TPC":
        joined = joined.rename(columns={tpc_col: "TPC"})
    return joined


# ──────────────────────────────────────────────────────────────
# Ordering points ALONG the polygon boundary
# ──────────────────────────────────────────────────────────────


def _boundary_line(poly: Polygon | MultiPolygon) -> LineString | MultiLineString:
    """
    Return a LineString (or MultiLineString) representing the outer boundary.
    Works for both Polygon and MultiPolygon.
    """
    if isinstance(poly, Polygon):
        return LineString(poly.exterior.coords)
    # MultiPolygon → merge exterior rings into one multilinestring
    return unary_union([LineString(p.exterior.coords) for p in poly.geoms])


def order_along_boundary(
    poly_geom: Polygon | MultiPolygon,
    pts: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    Order *pts* clockwise along the actual polygon boundary.
    We project each point onto the boundary LineString and sort by that
    distance.  The inherent ring orientation already defines clockwise vs CCW
    but we only need adjacency, not absolute direction.
    """
    if pts.empty:
        return pts

    boundary = _boundary_line(poly_geom)
    pts = pts.copy()
    pts["__d__"] = pts.geometry.apply(boundary.project)
    return pts.sort_values("__d__").drop(columns="__d__").reset_index(drop=True)


# ──────────────────────────────────────────────────────────────
# Validation logic
# ──────────────────────────────────────────────────────────────


def check_tpc6_neighbours(
    ordered: pd.DataFrame,
    prefixes: Tuple[str, ...],
) -> list[dict]:
    """Return error rows for points that violate the neighbour rule."""
    n = len(ordered)
    if n < 2:
        return []

    errs: list[dict] = []
    for i, row in ordered.iterrows():
        if row["TPC"] != 6:
            continue
        pid = row["point_IDN"]
        if not pid.startswith(prefixes):
            continue  # point not in scope

        prev_tpc = ordered.iloc[(i - 1) % n]["TPC"]
        next_tpc = ordered.iloc[(i + 1) % n]["TPC"]

        if prev_tpc != 1 and next_tpc != 1:
            errs.append(
                dict(
                    Description="TPC=6 without adjacent TPC=1",
                    IDN=pid,
                    TPC=row["TPC"],
                    Polygon_IDN=row["polygon_IDN"],
                    Previous_TPC=prev_tpc,
                    Next_TPC=next_tpc,
                )
            )
    return errs


def run_validation(
    polys: gpd.GeoDataFrame,
    joined: gpd.GeoDataFrame,
    prefixes: Tuple[str, ...],
) -> list[dict]:
    """Validate every prefix‑filtered polygon & collect any violations."""
    errors: list[dict] = []
    for _, poly in polys.iterrows():
        pid = poly["polygon_IDN"]
        pts = joined.loc[joined["polygon_IDN"] == pid]
        if pts.empty:
            continue
        ordered = order_along_boundary(poly.geometry, pts)
        errors.extend(check_tpc6_neighbours(ordered, prefixes))
    return errors


# ──────────────────────────────────────────────────────────────
# Reporting
# ──────────────────────────────────────────────────────────────


def save_errors(errs: list[dict], csv_path: str) -> None:
    if errs:
        pd.DataFrame(errs).to_csv(csv_path, index=False)
        print(f"\n❗ {len(errs):,} error(s) written to «{csv_path}»")
    else:
        print("\n✅ No validation errors found.")


# ──────────────────────────────────────────────────────────────
# CLI helpers
# ──────────────────────────────────────────────────────────────


def get_inputs() -> Tuple[str, str, Tuple[str, ...], str]:
    print("=== GIS Polygon–Point Validation Tool ===\n")
    gbg = input("Path to gbg.shp : ").strip().strip('"')
    gvp = input("Path to gvp.shp : ").strip().strip('"')
    prefixes = tuple(
        p.strip() for p in input("IDN prefix(es) (comma‑sep.): ").split(",") if p.strip()
    )
    out_csv = input("Output CSV path        : ").strip().strip('"')

    for path in (gbg, gvp):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
    if not prefixes:
        raise ValueError("At least one prefix is required.")
    if not out_csv:
        raise ValueError("CSV output path is required.")
    return gbg, gvp, prefixes, out_csv


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────


def main() -> None:
    try:
        gbg_path, gvp_path, prefixes, out_csv = get_inputs()

        gbg = load_polygons(gbg_path, prefixes)
        if gbg.empty:
            print("⚠ No polygons match the provided prefix(es).")
            sys.exit(0)

        gvp = load_points(gvp_path)
        joined = associate_points(gvp, gbg)

        if joined["polygon_IDN"].notna().sum() == 0:
            print("\n⚠ No points intersect the filtered polygons. Check CRS/geometry.")
            sys.exit(1)

        errors = run_validation(gbg, joined, prefixes)
        save_errors(errors, out_csv)

    except KeyboardInterrupt:
        print("\n⏹ Interrupted.")
    except Exception as exc:
        print(f"\n❌ {exc}")
        traceback.print_exc(limit=1)


if __name__ == "__main__":
    main()
