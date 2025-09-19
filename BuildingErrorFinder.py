import sys, subprocess

# Auto-install required packages
required_packages = ["laspy", "numpy", "scipy", "geopandas", "shapely", "scikit-learn", "PyQt5"]
for pkg in required_packages:
    try:
        __import__(pkg.split("==")[0])
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg])

import laspy, numpy as np, geopandas as gpd
from scipy.spatial import cKDTree
from shapely.geometry import Point
from sklearn.decomposition import PCA
from PyQt5.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QFileDialog,
    QVBoxLayout, QHBoxLayout, QMessageBox, QProgressBar
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal

# --- Building error detection in chunks ---
def detect_building_errors(x, y, z, slope_tol, planar_tol, min_pts, max_height, radius, min_planarity_height, progress_callback=None):
    coords = np.vstack((x, y)).T
    tree = cKDTree(coords)
    errors, etypes = [], []

    total = len(x)
    for i, (px, py, pz) in enumerate(zip(x, y, z)):
        # --- Ignore points below planarity threshold ---
        if pz < min_planarity_height:
            continue

        idx = tree.query_ball_point([px, py], r=radius)
        if len(idx) < min_pts:
            errors.append((px, py, pz)); etypes.append("LOW_DENSITY")
        else:
            neigh = np.vstack((x[idx], y[idx], z[idx])).T
            pca = PCA(n_components=3).fit(neigh)
            eigenvals = pca.explained_variance_

            if eigenvals[1] / eigenvals[0] > planar_tol:
                errors.append((px, py, pz)); etypes.append("NON_PLANAR")

            slope = np.arctan(np.sqrt(eigenvals[0] / eigenvals[2])) * 180 / np.pi
            if slope > slope_tol:
                errors.append((px, py, pz)); etypes.append("HIGH_SLOPE")

            if pz > max_height:
                errors.append((px, py, pz)); etypes.append("HEIGHT_EXCEED")

        # --- Progress update ---
        if progress_callback and i % 500 == 0:  # update every 500 points
            progress_callback(int((i / total) * 100))

    if progress_callback:
        progress_callback(100)

    return errors, etypes

# --- Worker thread for GUI responsiveness ---
class Worker(QThread):
    finished = pyqtSignal(int)
    error = pyqtSignal(str)
    progress = pyqtSignal(int)

    def __init__(self, input_file, output_file, slope_tol, planar_tol, min_pts, max_height, radius, epsg, min_planarity_height):
        super().__init__()
        self.input_file = input_file
        self.output_file = output_file
        self.slope_tol = slope_tol
        self.planar_tol = planar_tol
        self.min_pts = min_pts
        self.max_height = max_height
        self.radius = radius
        self.epsg = epsg
        self.min_planarity_height = min_planarity_height

    def run(self):
        try:
            las = laspy.read(self.input_file)
            mask = las.classification == 6  # building points
            x, y, z = las.x[mask], las.y[mask], las.z[mask]

            errors, etypes = detect_building_errors(
                x, y, z,
                self.slope_tol, self.planar_tol,
                self.min_pts, self.max_height,
                self.radius, self.min_planarity_height,
                progress_callback=self.progress.emit
            )

            if errors:
                gdf = gpd.GeoDataFrame({
                    "X": [px for px, _, _ in errors],
                    "Y": [py for _, py, _ in errors],
                    "Z": [pz for _, _, pz in errors],
                    "ErrorType": etypes
                }, geometry=[Point(px, py) for px, py, _ in errors], crs=f"EPSG:{self.epsg}")
                gdf.to_file(self.output_file)

            self.finished.emit(len(errors))
        except Exception as e:
            self.error.emit(str(e))

# --- GUI ---
class BuildingFinder(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Building Error Finder")
        self.setGeometry(300, 200, 600, 400)

        # Input/Output
        self.in_label, self.in_file, self.in_browse = QLabel("Input LAS/LAZ:"), QLineEdit(), QPushButton("Browse")
        self.in_browse.clicked.connect(self.browse_in)

        self.out_label, self.out_file, self.out_browse = QLabel("Output Shapefile:"), QLineEdit(), QPushButton("Browse")
        self.out_browse.clicked.connect(self.browse_out)

        # Parameters
        self.slope_label, self.slope = QLabel("Slope Tol (deg):"), QLineEdit("45")
        self.planar_label, self.planar = QLabel("Planarity Tol:"), QLineEdit("0.3")
        self.min_label, self.minpts = QLabel("Min Points:"), QLineEdit("10")
        self.h_label, self.height = QLabel("Max Height (m):"), QLineEdit("100")
        self.r_label, self.radius = QLabel("Search Radius (m):"), QLineEdit("3.0")
        self.epsg_label, self.epsg = QLabel("EPSG:"), QLineEdit("4326")
        self.ph_label, self.planarity_height = QLabel("Min Planarity Height (m):"), QLineEdit("2.0")

        # Run + Progress
        self.run_btn = QPushButton("Run Detection")
        self.run_btn.clicked.connect(self.run_detection)
        self.progress = QProgressBar()
        self.progress.setAlignment(Qt.AlignCenter)

        layout = QVBoxLayout()
        for widgets in [
            (self.in_label, self.in_file, self.in_browse),
            (self.out_label, self.out_file, self.out_browse),
            (self.slope_label, self.slope),
            (self.planar_label, self.planar),
            (self.min_label, self.minpts),
            (self.h_label, self.height),
            (self.r_label, self.radius),
            (self.epsg_label, self.epsg),
            (self.ph_label, self.planarity_height),
        ]:
            hl = QHBoxLayout()
            for w in widgets: hl.addWidget(w)
            layout.addLayout(hl)

        layout.addWidget(self.run_btn)
        layout.addWidget(self.progress)
        self.setLayout(layout)

    def browse_in(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select LAS/LAZ", "", "LiDAR (*.las *.laz)")
        if f: self.in_file.setText(f)

    def browse_out(self):
        f, _ = QFileDialog.getSaveFileName(self, "Save Shapefile", "", "Shapefile (*.shp)")
        if f:
            if not f.endswith(".shp"): f += ".shp"
            self.out_file.setText(f)

    def run_detection(self):
        try:
            slope, planar = float(self.slope.text()), float(self.planar.text())
            minpts, height = int(self.minpts.text()), float(self.height.text())
            rad, epsg = float(self.radius.text()), int(self.epsg.text())
            min_planarity_height = float(self.planarity_height.text())

            self.worker = Worker(
                self.in_file.text().strip(), self.out_file.text().strip(),
                slope, planar, minpts, height, rad, epsg, min_planarity_height
            )
            self.worker.progress.connect(self.progress.setValue)
            self.worker.finished.connect(lambda count: QMessageBox.information(self, "Done", f"Building errors: {count}"))
            self.worker.error.connect(lambda e: QMessageBox.critical(self, "Error", e))

            self.worker.start()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = BuildingFinder()
    win.show()
    sys.exit(app.exec_())
