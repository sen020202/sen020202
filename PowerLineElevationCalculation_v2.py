import geopandas as gpd
import pandas as pd
import numpy as np
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from shapely.geometry import Point, Polygon, box
import traceback
from typing import Tuple, List

class PowerlineAnalysisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Powerline Elevation Analysis")
        self.root.geometry("800x500")

        # Variables
        self.folder_path = tk.StringVar()

        self.setup_gui()

    def setup_gui(self):
        folder_frame = ttk.LabelFrame(self.root, text="Input Folder", padding="10")
        folder_frame.pack(fill="x", padx=10, pady=5)

        ttk.Entry(folder_frame, textvariable=self.folder_path, width=70).pack(side="left", padx=5)
        ttk.Button(folder_frame, text="Browse", command=self.browse_folder).pack(side="left")

        self.progress_frame = ttk.LabelFrame(self.root, text="Progress", padding="10")
        self.progress_frame.pack(fill="x", padx=10, pady=5)

        self.progress_bar = ttk.Progressbar(self.progress_frame, length=600, mode='determinate')
        self.progress_bar.pack(fill="x", padx=5, pady=5)

        status_frame = ttk.LabelFrame(self.root, text="Status Messages", padding="10")
        status_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.status_text = tk.Text(status_frame, height=10, wrap=tk.WORD)
        self.status_text.pack(fill="both", expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(self.status_text, command=self.status_text.yview)
        scrollbar.pack(side="right", fill="y")
        self.status_text.configure(yscrollcommand=scrollbar.set)

        ttk.Button(self.root, text="Process Files", command=self.process_files).pack(pady=10)

    def browse_folder(self):
        """Open a folder dialog to select the input folder."""
        folder_selected = filedialog.askdirectory()
        if folder_selected:
            self.folder_path.set(folder_selected)

    def log_message(self, message: str):
        """Log a message to the status text box."""
        self.status_text.insert(tk.END, message + "\n")
        self.status_text.see(tk.END)

    def create_highlight_box(self, x: float, y: float, size: float = 5.0) -> Polygon:
        """
        Create a square polygon centered at the given coordinates.
        
        Args:
            x (float): X coordinate of center point
            y (float): Y coordinate of center point
            size (float): Size of the box in units of the coordinate system
        
        Returns:
            Polygon: Square polygon centered at (x,y)
        """
        half_size = size / 2
        return box(x - half_size, y - half_size, x + half_size, y + half_size)

    def create_highlight_shapefile(self, results_df: pd.DataFrame, input_crs, output_path: str):
        """
        Create a shapefile with polygons at minimum and maximum elevation points.
        
        Args:
            results_df (pd.DataFrame): DataFrame containing analysis results
            input_crs: Coordinate reference system from input shapefile
            output_path (str): Path to save the output shapefile
        """
        highlight_features = []

        for _, row in results_df.iterrows():
            # Create polygon for minimum elevation point
            min_poly = self.create_highlight_box(row['min_x'], row['min_y'])
            highlight_features.append({
                'geometry': min_poly,
                'element_id': row['element_id'],
                'point_type': 'Minimum Elevation',
                'elevation_diff': row['min_elev_diff']
            })

            # Create polygon for maximum elevation point
            max_poly = self.create_highlight_box(row['max_x'], row['max_y'])
            highlight_features.append({
                'geometry': max_poly,
                'element_id': row['element_id'],
                'point_type': 'Maximum Elevation',
                'elevation_diff': row['max_elev_diff']
            })

        # Create GeoDataFrame with the highlight polygons
        highlight_gdf = gpd.GeoDataFrame(highlight_features, crs=input_crs)
        highlight_gdf.to_file(output_path)

        return highlight_gdf

    def find_min_max_elevations(self, ground_cable: gpd.GeoDataFrame, sky_cable: gpd.GeoDataFrame) -> pd.DataFrame:
        """
        Find minimum and maximum elevation differences between ground and sky cables.

        Args:
            ground_cable (gpd.GeoDataFrame): GeoDataFrame with ground cable features
            sky_cable (gpd.GeoDataFrame): GeoDataFrame with sky cable features

        Returns:
            pd.DataFrame: DataFrame with elevation analysis results
        """
        results = []

        for ground_geom, sky_geom in zip(ground_cable.geometry, sky_cable.geometry):
            if ground_geom.is_empty or sky_geom.is_empty:
                continue

            ground_coords = np.array(ground_geom.coords)
            sky_coords = np.array(sky_geom.coords)

            min_diff = float('inf')
            max_diff = float('-inf')

            min_point = None
            max_point = None

            for g_point in ground_coords:
                for s_point in sky_coords:
                    diff = s_point[2] - g_point[2]  # Assuming 3D coordinates (x, y, z)
                    if diff < min_diff:
                        min_diff = diff
                        min_point = g_point

                    if diff > max_diff:
                        max_diff = diff
                        max_point = g_point

            if min_point is not None and max_point is not None:
                results.append({
                    'element_id': len(results) + 1,
                    'min_x': min_point[0], 'min_y': min_point[1], 'min_elev_diff': min_diff.round(3),
                    'max_x': max_point[0], 'max_y': max_point[1], 'max_elev_diff': max_diff.round(3)
                })

        return pd.DataFrame(results)

    def process_files(self):
        if not self.folder_path.get():
            messagebox.showerror("Error", "Please select input folder!")
            return

        try:
            self.status_text.delete(1.0, tk.END)  # Clear previous messages
            input_folder = self.folder_path.get()
            output_folder = os.path.join(input_folder, "elevation_reports")
            os.makedirs(output_folder, exist_ok=True)

            # Find all shapefiles in the folder
            shp_files = [f for f in os.listdir(input_folder) if f.endswith('.shp')]

            if not shp_files:
                self.log_message("No shapefiles found in the selected folder!")
                return

            self.log_message(f"Found {len(shp_files)} shapefile(s) to process")

            for shp_file in shp_files:
                self.log_message(f"\nProcessing {shp_file}...")
                self.progress_bar['value'] = 0

                # Read the shapefile
                file_path = os.path.join(input_folder, shp_file)
                gdf = gpd.read_file(file_path)

                # Store the CRS for later use
                input_crs = gdf.crs

                # Check if Layer attribute exists
                if 'Layer' not in gdf.columns:
                    self.log_message(f"Error: Layer attribute not found in {shp_file}")
                    continue

                # Split data into top and bottom levels
                bottom_cable = gdf[gdf['Layer'] == 'BottomLevel'].copy()
                top_cable = gdf[gdf['Layer'] == 'UpperLevel'].copy()

                if len(bottom_cable) == 0:
                    self.log_message(f"Error: No BottomLevel features found in {shp_file}")
                    continue

                if len(top_cable) == 0:
                    self.log_message(f"Error: No UpperLevel features found in {shp_file}")
                    continue

                self.log_message(f"Found {len(bottom_cable)} bottom level and {len(top_cable)} upper level features")

                self.progress_bar['value'] = 30
                self.log_message("Calculating elevation differences...")

                # Process elevation differences
                results_df = self.find_min_max_elevations(bottom_cable, top_cable)

                if len(results_df) == 0:
                    self.log_message("Warning: No valid results generated for this file")
                    continue

                self.progress_bar['value'] = 70
                self.log_message("Saving results...")

                # Save CSV results
                base_name = os.path.splitext(shp_file)[0]
                csv_output = os.path.join(output_folder, f"elevation_report_{base_name}.csv")
                results_df.to_csv(csv_output, index=False)

                # Create and save highlight shapefile
                highlight_output = os.path.join(output_folder, f"elevation_points_{base_name}.shp")
                self.log_message("Creating highlight shapefile...")
                self.create_highlight_shapefile(results_df, input_crs, highlight_output)

                self.progress_bar['value'] = 100
                self.log_message(f"Successfully saved results to:")
                self.log_message(f"1. CSV report: {csv_output}")
                self.log_message(f"2. Highlight shapefile: {highlight_output}")

            self.log_message("\nProcessing complete!")
            messagebox.showinfo("Success", f"Analysis complete!\nResults saved to:\n{output_folder}")

        except Exception as e:
            error_msg = f"Error details:\n{str(e)}\n\nStacktrace:\n{traceback.format_exc()}"
            self.log_message(error_msg)
            messagebox.showerror("Error", "An error occurred during processing.\nPlease check the status messages for details.")

def main():
    root = tk.Tk()
    app = PowerlineAnalysisGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()