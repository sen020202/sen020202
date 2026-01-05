#!/usr/bin/env python3
"""
LiDAR Non-HardSurface Finder - Extended Version
------------------------------------------------
Features:
1. Auto-install missing dependencies.
2. Detect isolated building points:
   - Based on minimum distance
   - AND maximum number of neighbor points
   - Save isolated points to error DXF, then delete them.
3. Detect hard surfaces:
   - First tolerance (tol1, in meters): classify as class 9
   - Second tolerance (tol2, in meters): expand around class 9 points
   - Additional slope tolerance (in degrees)
4. Delete points below average building elevation.
5. Create 3D building polygons from remaining class 6 points.
6. Save outputs:
   - Error DXF (isolated points)
   - Building DXF (3D polygons)
"""

import sys, subprocess, traceback, os, glob, math

# ---------------- Dependency Installer ---------------- #
REQUIRED_LIBS = ["laspy", "numpy", "scipy", "shapely", "ezdxf", "tk", "scikit-learn"]

def install_missing():
    for lib in REQUIRED_LIBS:
        try:
            __import__(lib if lib != "tk" else "tkinter")
        except ImportError:
            print(f"[INFO] Installing missing dependency: {lib}")
            subprocess.check_call([sys.executable, "-m", "pip", "install", lib])

try:
    install_missing()
except Exception as e:
    print("[FATAL] Could not install dependencies:", e)
    traceback.print_exc()
    input("\nPress Enter to exit...")
    sys.exit(1)

# ---------------- Imports ---------------- #
import laspy
import numpy as np
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint, Polygon
import ezdxf
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from sklearn.neighbors import NearestNeighbors

# ---------------- Utility Functions ---------------- #

def load_points(las_file):
    las = laspy.read(las_file)
    return np.vstack((las.x, las.y, las.z, las.classification)).T

def find_isolated_points(points, min_pts=1, min_dist=2.0, max_pts=5):
    tree = cKDTree(points[:, :3])
    counts = tree.query_ball_point(points[:, :3], min_dist)
    iso_mask = np.array([(len(c) <= min_pts) or (len(c) <= max_pts) for c in counts])
    return points[iso_mask], points[~iso_mask]

def reclassify_hard_surface(points, tol1=0.2, tol2=0.5, slope_tol=5.0, knn_k=20):
    """Classify points within tolerances or slope angle as hard surface (class 9)."""
    new_points = points.copy()
    if len(points) == 0:
        return new_points

    z_mean = np.mean(points[:, 2])

    # Height tolerances
    mask1 = np.abs(points[:, 2] - z_mean) <= tol1
    mask2 = np.abs(points[:, 2] - z_mean) <= tol2

    # Slope tolerance
    X = points[:, :3]
    nbrs = NearestNeighbors(n_neighbors=knn_k, algorithm='auto').fit(X)
    _, indices = nbrs.kneighbors(X)

    slope_mask = np.zeros(len(points), dtype=bool)
    for i, neigh_idx in enumerate(indices):
        neigh_pts = X[neigh_idx]
        centroid = neigh_pts.mean(axis=0)
        centered = neigh_pts - centroid
        U, S, Vt = np.linalg.svd(centered, full_matrices=False)
        normal = Vt[-1, :]
        if normal[2] < 0:
            normal = -normal
        nx, ny, nz = normal
        slope_rad = math.atan2(math.sqrt(nx * nx + ny * ny), abs(nz))
        slope_deg = math.degrees(slope_rad)
        if slope_deg <= slope_tol:
            slope_mask[i] = True

    combined_mask = mask1 | mask2 | slope_mask
    new_points[combined_mask, 3] = 9
    return new_points

def delete_negative(points, ref_points):
    if len(ref_points) == 0:
        return points
    ref_z = np.mean(ref_points[:, 2])
    return points[points[:, 2] >= ref_z]

def cluster_points(points, radius=0.5):
    tree = cKDTree(points[:, :2])
    visited = np.zeros(len(points), dtype=bool)
    clusters = []
    for i, p in enumerate(points):
        if visited[i]:
            continue
        idx = tree.query_ball_point(p[:2], radius)
        cluster = points[idx]
        visited[idx] = True
        clusters.append(cluster)
    return clusters

def create_polygons(points, radius=0.5):
    clusters = cluster_points(points, radius)
    polygons = []
    for cluster in clusters:
        if len(cluster) >= 3:
            hull = MultiPoint(cluster[:, :2]).convex_hull
            if isinstance(hull, Polygon):
                avg_z = float(np.mean(cluster[:, 2]))
                coords = [(x, y, avg_z) for x, y in hull.exterior.coords]
                polygons.append(coords)
    return polygons

def save_error_dxf(points, out_file):
    doc = ezdxf.new(dxfversion="R2018")
    msp = doc.modelspace()
    for p in points:
        msp.add_point((p[0], p[1], p[2]), dxfattribs={"layer": "Isolated"})
    doc.saveas(out_file)

def save_polygon_dxf(polygons, out_file):
    doc = ezdxf.new(dxfversion="R2018")
    msp = doc.modelspace()
    for poly in polygons:
        msp.add_lwpolyline(poly, format="xyz", dxfattribs={"layer": "Buildings", "closed": True})
    doc.saveas(out_file)

# ---------------- Main Processing ---------------- #

def process_file(las_file, out_dir, min_dist, min_pts, max_pts, tol1, tol2, slope_tol, radius):
    points = load_points(las_file)
    class6 = points[points[:, 3] == 6]

    # 1. Isolated points
    isolated, class6_clean = find_isolated_points(class6, min_pts=min_pts, min_dist=min_dist, max_pts=max_pts)
    if len(isolated) > 0:
        err_file = os.path.join(out_dir, os.path.splitext(os.path.basename(las_file))[0] + "_isolated.dxf")
        save_error_dxf(isolated, err_file)

    # 2. Hard surface classification with slope tolerance
    class9 = reclassify_hard_surface(class6_clean, tol1=tol1, tol2=tol2, slope_tol=slope_tol)

    # 3. Delete negative points
    filtered = delete_negative(class9, class6_clean)

    # 4. Create polygons
    polygons = create_polygons(filtered, radius=radius)

    # Save final polygons
    out_file = os.path.join(out_dir, os.path.splitext(os.path.basename(las_file))[0] + "_buildings.dxf")
    save_polygon_dxf(polygons, out_file)

# ---------------- GUI ---------------- #

def run_gui():
    root = tk.Tk()
    root.title("LiDAR Non-HardSurface Finder")

    tk.Label(root, text="Input Folder:").grid(row=0, column=0, sticky="w")
    input_entry = tk.Entry(root, width=50); input_entry.grid(row=0, column=1)
    tk.Button(root, text="Browse", command=lambda: input_entry.insert(0, filedialog.askdirectory())).grid(row=0, column=2)

    tk.Label(root, text="Output Folder:").grid(row=1, column=0, sticky="w")
    output_entry = tk.Entry(root, width=50); output_entry.grid(row=1, column=1)
    tk.Button(root, text="Browse", command=lambda: output_entry.insert(0, filedialog.askdirectory())).grid(row=1, column=2)

    tk.Label(root, text="Min Distance (isolated):").grid(row=2, column=0, sticky="w")
    dist_entry = tk.Entry(root); dist_entry.insert(0, "2.0"); dist_entry.grid(row=2, column=1)

    tk.Label(root, text="Min Points (isolated):").grid(row=3, column=0, sticky="w")
    minpts_entry = tk.Entry(root); minpts_entry.insert(0, "1"); minpts_entry.grid(row=3, column=1)

    tk.Label(root, text="Max Points (isolated):").grid(row=4, column=0, sticky="w")
    maxpts_entry = tk.Entry(root); maxpts_entry.insert(0, "5"); maxpts_entry.grid(row=4, column=1)

    tk.Label(root, text="Tolerance 1 (hard surface):").grid(row=5, column=0, sticky="w")
    tol1_entry = tk.Entry(root); tol1_entry.insert(0, "0.2"); tol1_entry.grid(row=5, column=1)

    tk.Label(root, text="Tolerance 2 (expand):").grid(row=6, column=0, sticky="w")
    tol2_entry = tk.Entry(root); tol2_entry.insert(0, "0.5"); tol2_entry.grid(row=6, column=1)

    tk.Label(root, text="Slope Tolerance (deg):").grid(row=7, column=0, sticky="w")
    slope_entry = tk.Entry(root); slope_entry.insert(0, "5.0"); slope_entry.grid(row=7, column=1)

    tk.Label(root, text="Polygon Radius:").grid(row=8, column=0, sticky="w")
    radius_entry = tk.Entry(root); radius_entry.insert(0, "0.5"); radius_entry.grid(row=8, column=1)

    progress = ttk.Progressbar(root, length=300, mode="determinate")
    progress.grid(row=9, column=0, columnspan=3, pady=10)

    def start():
        in_dir = input_entry.get()
        out_dir = output_entry.get()
        min_dist = float(dist_entry.get())
        min_pts = int(minpts_entry.get())
        max_pts = int(maxpts_entry.get())
        tol1 = float(tol1_entry.get())
        tol2 = float(tol2_entry.get())
        slope_tol = float(slope_entry.get())
        radius = float(radius_entry.get())

        files = glob.glob(os.path.join(in_dir, "*.las")) + glob.glob(os.path.join(in_dir, "*.laz"))
        progress["maximum"] = len(files)
        for i, f in enumerate(files):
            try:
                process_file(f, out_dir, min_dist, min_pts, max_pts, tol1, tol2, slope_tol, radius)
            except Exception as e:
                messagebox.showerror("Error", f"Failed {f}: {str(e)}")
            progress["value"] = i + 1
            root.update_idletasks()
        messagebox.showinfo("Done", "Processing completed!")

    tk.Button(root, text="Start", command=start).grid(row=10, column=1, pady=10)
    root.mainloop()

# ---------------- Entry Point ---------------- #

if __name__ == "__main__":
    try:
        run_gui()
    except Exception as e:
        print("\n[CRITICAL ERROR] Tool crashed!")
        print(str(e))
        traceback.print_exc()
        with open("error.log", "w") as f:
            f.write("[CRITICAL ERROR]\n")
            f.write(str(e) + "\n\n")
            f.write(traceback.format_exc())
        input("\nPress Enter to exit...")
        sys.exit(1)
