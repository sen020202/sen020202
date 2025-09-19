import os
import sys
import traceback
import threading
import csv
import math
from tkinter import (
    Tk, filedialog, ttk, Label, Entry, Button, StringVar, IntVar, DoubleVar,
    BooleanVar, Text, END, W, E, N, S, Scrollbar, VERTICAL, HORIZONTAL
)
import laspy
import numpy as np
from scipy.spatial import cKDTree
import ezdxf
from tqdm import tqdm

# ------- Helper functions -------

def safe_makedirs(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def is_las_file(path):
    ext = os.path.splitext(path)[1].lower()
    return ext in ('.las', '.laz')

def list_las_files(folder, recursive=False):
    out = []
    if recursive:
        for root, dirs, files in os.walk(folder):
            for f in files:
                if is_las_file(f) or is_las_file(os.path.join(root, f)):
                    out.append(os.path.join(root, f))
    else:
        for f in os.listdir(folder):
            full = os.path.join(folder, f)
            if os.path.isfile(full) and is_las_file(full):
                out.append(full)
    out.sort()
    return out

# connected components using KDTree neighbors (graph BFS)
def compute_clusters_xy(xy, cluster_eps):
    """
    xy: Nx2 array
    cluster_eps: radius to link points into same cluster
    returns labels array (N,) of cluster ids (0..k-1)
    """
    n = xy.shape[0]
    if n == 0:
        return np.array([], dtype=int)
    tree = cKDTree(xy)
    # for each point get neighbors within eps
    neighbors = tree.query_ball_tree(tree, r=cluster_eps)
    labels = -np.ones(n, dtype=int)
    current_label = 0
    for i in range(n):
        if labels[i] != -1:
            continue
        # BFS
        stack = [i]
        labels[i] = current_label
        while stack:
            u = stack.pop()
            for v in neighbors[u]:
                if labels[v] == -1:
                    labels[v] = current_label
                    stack.append(v)
        current_label += 1
    return labels

def find_nonplanar_indices(xy, z, overlap_xy_radius, overlap_z_threshold):
    """
    Mark points that have another point within overlap_xy_radius and
    that other point is lower by more than overlap_z_threshold.
    We flag the higher point as non-planar (error).
    Returns boolean mask (N,) where True = non-planar error.
    """
    n = xy.shape[0]
    mask = np.zeros(n, dtype=bool)
    if n == 0:
        return mask
    tree = cKDTree(xy)
    # query neighbors for each point (excluding itself)
    neighbors_list = tree.query_ball_point(xy, r=overlap_xy_radius)
    for i, neigh in enumerate(neighbors_list):
        # skip itself
        for j in neigh:
            if j == i:
                continue
            # If i is higher than j by more than threshold -> i is error
            if z[i] - z[j] > overlap_z_threshold:
                mask[i] = True
                break
            # Conversely if j is higher than i by threshold -> j is error
            if z[j] - z[i] > overlap_z_threshold:
                mask[j] = True
    return mask

# Write DXF with two point layers
def write_dxf_points(output_path, points_xyz, layer_name, color_index=1):
    """
    Append points to an existing DXF doc or create new if not exists.
    points_xyz: Nx3 array
    layer_name: str
    """
    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    # create layer if not exist
    if layer_name not in doc.layers:
        doc.layers.new(layer_name)
    for pt in points_xyz:
        # write as POINT entity (DXF POINT)
        msp.add_point((float(pt[0]), float(pt[1]), float(pt[2])), dxfattribs={'layer': layer_name})
    doc.saveas(output_path)

# Better: create DXF doc with two layers and write points to each
def write_error_dxf(output_path, isolated_xyz, nonplanar_xyz):
    doc = ezdxf.new(dxfversion="R2010")
    msp = doc.modelspace()
    # create layers
    if 'ERROR_ISOLATED' not in doc.layers:
        doc.layers.new('ERROR_ISOLATED', dxfattribs={'color': 1})
    if 'ERROR_NONPLANAR' not in doc.layers:
        doc.layers.new('ERROR_NONPLANAR', dxfattribs={'color': 3})
    # add points
    for pt in isolated_xyz:
        msp.add_point((float(pt[0]), float(pt[1]), float(pt[2])), dxfattribs={'layer': 'ERROR_ISOLATED'})
    for pt in nonplanar_xyz:
        msp.add_point((float(pt[0]), float(pt[1]), float(pt[2])), dxfattribs={'layer': 'ERROR_NONPLANAR'})
    doc.saveas(output_path)

# ------- Core processing for a single file -------
def process_las_file(
    input_path,
    output_dir,
    cluster_eps,
    cluster_size_threshold,
    overlap_xy_radius,
    overlap_z_threshold,
    write_csv=True,
    logger=None
):
    """
    Processes a single LAS/LAZ file:
    - extracts class 6 (building) points,
    - finds isolated clusters (cluster_eps) whose size <= cluster_size_threshold
    - finds non-planar overlap points (overlap_xy_radius & overlap_z_threshold)
    - writes <basename>_error.dxf and <basename>_errors.csv
    """
    basename = os.path.splitext(os.path.basename(input_path))[0]
    out_dxf = os.path.join(output_dir, f"{basename}_error.dxf")
    out_csv = os.path.join(output_dir, f"{basename}_errors.csv")
    try:
        if logger:
            logger(f"Reading: {input_path}")
        las = laspy.read(input_path)
    except Exception as e:
        if logger:
            logger(f"ERROR reading {input_path}: {e}")
        return {'file': input_path, 'status': 'read_error', 'error': str(e)}

    try:
        classes = las.classification
        # find building points as per ASPRS class 6
        building_mask = (classes == 6)
        total_building = np.count_nonzero(building_mask)
        if logger:
            logger(f"Total points: {len(classes):,}, building points: {total_building:,}")

        if total_building == 0:
            if logger:
                logger("No building points found. Writing empty DXF with no points.")
            # create empty DXF
            write_error_dxf(out_dxf, np.empty((0,3)), np.empty((0,3)))
            with open(out_csv, 'w', newline='') as fh:
                writer = csv.writer(fh)
                writer.writerow(['file','status','total_points','building_points'])
                writer.writerow([input_path,'no_buildings',len(classes),0])
            return {'file': input_path, 'status':'no_buildings', 'building_points':0}

        x = las.x[building_mask]
        y = las.y[building_mask]
        z = las.z[building_mask]
        xy = np.column_stack((x, y))

        # compute clusters using cluster_eps
        if logger:
            logger("Computing XY clusters for building points...")
        labels = compute_clusters_xy(xy, cluster_eps)
        # count cluster sizes
        unique, counts = np.unique(labels, return_counts=True)
        cluster_size_map = dict(zip(unique, counts))
        # isolated: any cluster size <= threshold
        isolated_mask = np.zeros_like(labels, dtype=bool)
        for lbl, cnt in cluster_size_map.items():
            if cnt <= cluster_size_threshold:
                isolated_mask[labels == lbl] = True
        isolated_count = np.count_nonzero(isolated_mask)
        if logger:
            logger(f"Isolated points flagged: {isolated_count}")

        # non-planar / overlap detection
        if logger:
            logger("Detecting non-planar (overlap) points ...")
        nonplanar_mask = find_nonplanar_indices(xy, z, overlap_xy_radius, overlap_z_threshold)
        nonplanar_count = np.count_nonzero(nonplanar_mask)
        if logger:
            logger(f"Non-planar points flagged: {nonplanar_count}")

        # Ensure a point may be in both categories; that's OK.
        isolated_xyz = np.column_stack((x[isolated_mask], y[isolated_mask], z[isolated_mask])) if isolated_count>0 else np.empty((0,3))
        nonplanar_xyz = np.column_stack((x[nonplanar_mask], y[nonplanar_mask], z[nonplanar_mask])) if nonplanar_count>0 else np.empty((0,3))

        if logger:
            logger(f"Writing DXF: {out_dxf}")
        write_error_dxf(out_dxf, isolated_xyz, nonplanar_xyz)

        if write_csv:
            if logger:
                logger(f"Writing CSV summary: {out_csv}")
            with open(out_csv, 'w', newline='') as fh:
                writer = csv.writer(fh)
                writer.writerow(['file','total_points','building_points','isolated_points','nonplanar_points','cluster_eps','cluster_size_threshold','overlap_xy_radius','overlap_z_threshold'])
                writer.writerow([input_path, len(las.points), total_building, isolated_count, nonplanar_count, cluster_eps, cluster_size_threshold, overlap_xy_radius, overlap_z_threshold])

        if logger:
            logger("Done.")
        return {'file': input_path, 'status':'ok', 'building_points': total_building, 'isolated': int(isolated_count), 'nonplanar': int(nonplanar_count)}
    except Exception as e:
        tb = traceback.format_exc()
        if logger:
            logger(f"Processing ERROR for {input_path}: {e}\n{tb}")
        return {'file': input_path, 'status':'process_error', 'error': str(e)}

# ------- GUI Application -------
class LidarValidatorGUI:
    def __init__(self, master):
        self.master = master
        master.title("LiDAR Building Validator — LAS/LAZ -> DXF errors")

        # Parameters (with default values)
        self.input_path = StringVar()
        self.output_path = StringVar()
        self.recursive = BooleanVar(value=False)

        self.cluster_eps = DoubleVar(value=1.0)  # meters to link cluster connectivity
        self.cluster_size_threshold = IntVar(value=25)  # <= this size => isolated
        self.overlap_xy_radius = DoubleVar(value=0.10)  # meters (10 cm)
        self.overlap_z_threshold = DoubleVar(value=0.15)  # meters (15 cm)

        # Layout
        row = 0
        Label(master, text="Input file or folder:").grid(row=row, column=0, sticky=W)
        Entry(master, textvariable=self.input_path, width=60).grid(row=row, column=1, columnspan=3, sticky=W+E)
        Button(master, text="Browse...", command=self.browse_input).grid(row=row, column=4, sticky=W)
        row += 1

        Label(master, text="Output folder:").grid(row=row, column=0, sticky=W)
        Entry(master, textvariable=self.output_path, width=60).grid(row=row, column=1, columnspan=3, sticky=W+E)
        Button(master, text="Browse...", command=self.browse_output).grid(row=row, column=4, sticky=W)
        row += 1

        Label(master, text="Process folder recursively:").grid(row=row, column=0, sticky=W)
        ttk.Checkbutton(master, variable=self.recursive).grid(row=row, column=1, sticky=W)
        row += 1

        Label(master, text="Cluster connectivity (cluster_eps, m):").grid(row=row, column=0, sticky=W)
        Entry(master, textvariable=self.cluster_eps).grid(row=row, column=1, sticky=W)
        Label(master, text="Cluster size threshold (≤):").grid(row=row, column=2, sticky=W)
        Entry(master, textvariable=self.cluster_size_threshold).grid(row=row, column=3, sticky=W)
        row += 1

        Label(master, text="Overlap XY radius (m):").grid(row=row, column=0, sticky=W)
        Entry(master, textvariable=self.overlap_xy_radius).grid(row=row, column=1, sticky=W)
        Label(master, text="Overlap Z threshold (m):").grid(row=row, column=2, sticky=W)
        Entry(master, textvariable=self.overlap_z_threshold).grid(row=row, column=3, sticky=W)
        row += 1

        Button(master, text="Start Processing", command=self.start_processing, width=20).grid(row=row, column=1, pady=8)
        Button(master, text="Stop (kill thread)", command=self.stop_processing, width=18).grid(row=row, column=2, pady=8)
        row += 1

        Label(master, text="Log:").grid(row=row, column=0, sticky=W)
        row += 1

        self.log_text = Text(master, height=18, width=100)
        self.log_text.grid(row=row, column=0, columnspan=5, sticky=W+E+N+S)
        # Scrollbars
        yscr = Scrollbar(master, orient=VERTICAL, command=self.log_text.yview)
        yscr.grid(row=row, column=5, sticky=N+S)
        self.log_text['yscrollcommand'] = yscr.set

        self._worker = None
        self._stop_flag = threading.Event()

    def browse_input(self):
        path = filedialog.askopenfilename(title="Select LAS/LAZ file") or filedialog.askdirectory(title="Select folder with LAS/LAZ files")
        if path:
            self.input_path.set(path)

    def browse_output(self):
        path = filedialog.askdirectory(title="Select output folder")
        if path:
            self.output_path.set(path)

    def log(self, msg):
        self.log_text.insert(END, msg + "\n")
        self.log_text.see(END)
        self.log_text.update_idletasks()

    def start_processing(self):
        if self._worker and self._worker.is_alive():
            self.log("Processing is already running.")
            return
        inp = self.input_path.get().strip()
        outp = self.output_path.get().strip()
        if not inp:
            self.log("Please specify input file or folder.")
            return
        if not outp:
            self.log("Please specify output folder.")
            return
        safe_makedirs(outp)
        params = {
            'cluster_eps': float(self.cluster_eps.get()),
            'cluster_size_threshold': int(self.cluster_size_threshold.get()),
            'overlap_xy_radius': float(self.overlap_xy_radius.get()),
            'overlap_z_threshold': float(self.overlap_z_threshold.get()),
            'recursive': bool(self.recursive.get()),
            'input_path': inp,
            'output_path': outp
        }
        self._stop_flag.clear()
        self._worker = threading.Thread(target=self._process_worker, args=(params,), daemon=True)
        self._worker.start()

    def stop_processing(self):
        if self._worker and self._worker.is_alive():
            self._stop_flag.set()
            self.log("Stop requested; thread will exit after finishing current file.")
        else:
            self.log("No active processing thread.")

    def _process_worker(self, params):
        try:
            inp = params['input_path']
            outp = params['output_path']
            files = []
            if os.path.isdir(inp):
                files = list_las_files(inp, recursive=params['recursive'])
            elif os.path.isfile(inp) and is_las_file(inp):
                files = [inp]
            else:
                self.log(f"Input path not valid: {inp}")
                return
            if len(files) == 0:
                self.log("No LAS/LAZ files found.")
                return
            self.log(f"Found {len(files)} file(s).")
            results = []
            for fpath in files:
                if self._stop_flag.is_set():
                    self.log("Stop flag set; exiting loop.")
                    break
                self.log(f"--- Processing: {fpath}")
                res = process_las_file(
                    fpath,
                    outp,
                    cluster_eps=params['cluster_eps'],
                    cluster_size_threshold=params['cluster_size_threshold'],
                    overlap_xy_radius=params['overlap_xy_radius'],
                    overlap_z_threshold=params['overlap_z_threshold'],
                    write_csv=True,
                    logger=self.log
                )
                results.append(res)
            self.log("All done. Summary:")
            for r in results:
                self.log(str(r))
        except Exception as e:
            tb = traceback.format_exc()
            self.log(f"Unhandled error in worker: {e}\n{tb}")

# ------- Main entry -------
def main():
    root = Tk()
    app = LidarValidatorGUI(root)
    root.geometry("920x600")
    root.mainloop()

if __name__ == "__main__":
    main()
