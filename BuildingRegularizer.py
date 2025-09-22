"""
Building Regulariser GUI Application

A standalone GUI application for the DPIRD-DMA Building Regulariser library.
This application provides an intuitive interface for cleaning and regularising 
building footprints in geospatial data.

"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import os
import sys
import threading
import traceback
from pathlib import Path
import json
import logging
from typing import Optional, Dict, Any

# Check for required dependencies and provide helpful error messages
try:
    import geopandas as gpd
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
    import numpy as np
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Please install required packages:")
    print("pip install geopandas matplotlib pandas numpy")
    sys.exit(1)

try:
    from buildingregulariser import regularize_geodataframe
except ImportError:
    print("Building Regulariser library not found!")
    print("Please install it using:")
    print("pip install buildingregulariser")
    sys.exit(1)


class BuildingRegulariserGUI:
    """Main GUI application class for Building Regulariser."""
    
    def __init__(self, root):
        self.root = root
        self.root.title("Building Regulariser - Geospatial Data Cleaning Tool")
        self.root.geometry("600x650")
        
        # Application state
        self.input_file_path = tk.StringVar()
        self.output_file_path = tk.StringVar()
        self.buildings_gdf = None
        self.regularized_gdf = None
        self.processing = False
        
        # Configure logging
        self.setup_logging()
        
        # Initialize UI
        self.setup_ui()
        self.load_default_settings()
        
    def setup_logging(self):
        """Set up logging for the application."""
        self.logger = logging.getLogger('BuildingRegulariser')
        self.logger.setLevel(logging.INFO)
        
        # Create console handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
        
    def setup_ui(self):
        """Initialize the user interface."""
        # Create main frames
        self.create_menu()
        self.create_input_frame()
        self.create_parameters_frame()
        self.create_processing_frame()
        self.create_output_frame()
        self.create_status_frame()
        
    def create_menu(self):
        """Create the application menu bar."""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Load Settings...", command=self.load_settings)
        file_menu.add_command(label="Save Settings...", command=self.save_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.quit)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)
        
    def create_input_frame(self):
        """Create the input file selection frame."""
        input_frame = ttk.LabelFrame(self.root, text="Input Data", padding="10")
        input_frame.pack(fill="x", padx=10, pady=5)
        
        # Input file selection
        ttk.Label(input_frame, text="Building Footprints File:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(input_frame, textvariable=self.input_file_path, width=60).grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(input_frame, text="Browse...", command=self.browse_input_file).grid(row=1, column=1, padx=(5, 0), pady=2)
        
        # File info label
        self.file_info_label = ttk.Label(input_frame, text="", foreground="gray")
        self.file_info_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=2)
        
        input_frame.columnconfigure(0, weight=1)
        
    def create_parameters_frame(self):
        """Create the parameters configuration frame."""
        params_frame = ttk.LabelFrame(self.root, text="Regularisation Parameters", padding="10")
        params_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Create notebook for parameter tabs
        notebook = ttk.Notebook(params_frame)
        notebook.pack(fill="both", expand=True)
        
        # Basic parameters tab
        basic_frame = ttk.Frame(notebook)
        notebook.add(basic_frame, text="Basic Parameters")
        self.create_basic_parameters(basic_frame)
        
        # Advanced parameters tab
        advanced_frame = ttk.Frame(notebook)
        notebook.add(advanced_frame, text="Advanced Parameters")
        self.create_advanced_parameters(advanced_frame)
        
        # Neighbor alignment tab
        neighbor_frame = ttk.Frame(notebook)
        notebook.add(neighbor_frame, text="Neighbor Alignment")
        self.create_neighbor_parameters(neighbor_frame)
        
    def create_basic_parameters(self, parent):
        """Create basic parameter controls."""
        # Parallel threshold
        ttk.Label(parent, text="Parallel Threshold:").grid(row=0, column=0, sticky="w", pady=5)
        self.parallel_threshold = tk.DoubleVar(value=2.0)
        ttk.Scale(parent, from_=0.5, to=5.0, orient="horizontal", variable=self.parallel_threshold, 
                 length=125).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(parent, textvariable=self.parallel_threshold).grid(row=0, column=2, padx=5)
        
        # Simplify tolerance
        ttk.Label(parent, text="Simplify Tolerance:").grid(row=1, column=0, sticky="w", pady=5)
        self.simplify_tolerance = tk.DoubleVar(value=0.5)
        ttk.Scale(parent, from_=0.1, to=2.0, orient="horizontal", variable=self.simplify_tolerance,
                 length=125).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(parent, textvariable=self.simplify_tolerance).grid(row=1, column=2, padx=5)
        
        # Checkboxes
        self.simplify_enabled = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Enable Simplification", variable=self.simplify_enabled).grid(row=2, column=0, sticky="w", pady=5)
        
        self.allow_45_degree = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Allow 45° Angles", variable=self.allow_45_degree).grid(row=3, column=0, sticky="w", pady=5)
        
        self.allow_circles = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Allow Circles", variable=self.allow_circles).grid(row=4, column=0, sticky="w", pady=5)
        
        parent.columnconfigure(1, weight=1)
        
    def create_advanced_parameters(self, parent):
        """Create advanced parameter controls."""
        # Diagonal threshold reduction
        ttk.Label(parent, text="Diagonal Threshold Reduction:").grid(row=0, column=0, sticky="w", pady=5)
        self.diagonal_threshold_reduction = tk.DoubleVar(value=15.0)
        ttk.Scale(parent, from_=0.0, to=22.5, orient="horizontal", variable=self.diagonal_threshold_reduction,
                 length=125).grid(row=0, column=1, sticky="ew", pady=5)
        ttk.Label(parent, textvariable=self.diagonal_threshold_reduction).grid(row=0, column=2, padx=5)
        
        # Circle threshold
        ttk.Label(parent, text="Circle Detection Threshold:").grid(row=1, column=0, sticky="w", pady=5)
        self.circle_threshold = tk.DoubleVar(value=0.9)
        ttk.Scale(parent, from_=0.5, to=1.0, orient="horizontal", variable=self.circle_threshold,
                 length=125).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(parent, textvariable=self.circle_threshold).grid(row=1, column=2, padx=5)
        
        # Number of cores
        ttk.Label(parent, text="CPU Cores:").grid(row=2, column=0, sticky="w", pady=5)
        self.num_cores = tk.IntVar(value=1)
        cores_spinbox = ttk.Spinbox(parent, from_=1, to=os.cpu_count(), textvariable=self.num_cores, width=10)
        cores_spinbox.grid(row=2, column=1, sticky="w", pady=5)
        
        # Include metadata
        self.include_metadata = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Include Metadata in Output", variable=self.include_metadata).grid(row=3, column=0, sticky="w", pady=5)
        
        parent.columnconfigure(1, weight=1)
        
    def create_neighbor_parameters(self, parent):
        """Create neighbor alignment parameter controls."""
        # Neighbor alignment
        self.neighbor_alignment = tk.BooleanVar(value=False)
        ttk.Checkbutton(parent, text="Enable Neighbor Alignment", variable=self.neighbor_alignment).grid(row=0, column=0, sticky="w", pady=5)
        
        # Neighbor search distance
        ttk.Label(parent, text="Search Distance:").grid(row=1, column=0, sticky="w", pady=5)
        self.neighbor_search_distance = tk.DoubleVar(value=350.0)
        ttk.Scale(parent, from_=50.0, to=1000.0, orient="horizontal", variable=self.neighbor_search_distance,
                 length=125).grid(row=1, column=1, sticky="ew", pady=5)
        ttk.Label(parent, textvariable=self.neighbor_search_distance).grid(row=1, column=2, padx=5)
        
        # Max rotation
        ttk.Label(parent, text="Max Rotation (degrees):").grid(row=2, column=0, sticky="w", pady=5)
        self.neighbor_max_rotation = tk.DoubleVar(value=10.0)
        ttk.Scale(parent, from_=1.0, to=45.0, orient="horizontal", variable=self.neighbor_max_rotation,
                 length=125).grid(row=2, column=1, sticky="ew", pady=5)
        ttk.Label(parent, textvariable=self.neighbor_max_rotation).grid(row=2, column=2, padx=5)
        
        parent.columnconfigure(1, weight=1)
        
    def create_processing_frame(self):
        """Create the processing controls frame."""
        processing_frame = ttk.LabelFrame(self.root, text="Processing", padding="10")
        processing_frame.pack(fill="x", padx=10, pady=5)
        
        # Process button
        self.process_button = ttk.Button(processing_frame, text="Regularize Buildings", 
                                        command=self.start_processing, style="Accent.TButton")
        self.process_button.pack(side="left", padx=(0, 10))
        
        # Progress bar
        self.progress = ttk.Progressbar(processing_frame, mode='indeterminate')
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        # Preview button
        self.preview_button = ttk.Button(processing_frame, text="Preview Results", 
                                        command=self.preview_results, state="disabled")
        self.preview_button.pack(side="right")
        
    def create_output_frame(self):
        """Create the output configuration frame."""
        output_frame = ttk.LabelFrame(self.root, text="Output", padding="10")
        output_frame.pack(fill="x", padx=10, pady=5)
        
        # Output file selection
        ttk.Label(output_frame, text="Output File:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Entry(output_frame, textvariable=self.output_file_path, width=60).grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Button(output_frame, text="Browse...", command=self.browse_output_file).grid(row=1, column=1, padx=(5, 0), pady=2)
        
        # Save button
        self.save_button = ttk.Button(output_frame, text="Save Results", command=self.save_results, state="disabled")
        self.save_button.grid(row=1, column=2, padx=(5, 0), pady=2)
        
        output_frame.columnconfigure(0, weight=1)
        
    def create_status_frame(self):
        """Create the status and log frame."""
        status_frame = ttk.LabelFrame(self.root, text="Status & Logs", padding="10")
        status_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Status text area
        self.status_text = scrolledtext.ScrolledText(status_frame, height=8, state="disabled")
        self.status_text.pack(fill="both", expand=True)
        
    def browse_input_file(self):
        """Browse for input geospatial file."""
        filetypes = [
            ("All Supported", "*.gpkg *.shp *.geojson *.json"),
            ("GeoPackage", "*.gpkg"),
            ("Shapefile", "*.shp"),
            ("GeoJSON", "*.geojson *.json"),
            ("All Files", "*.*")
        ]
        
        filename = filedialog.askopenfilename(
            title="Select Building Footprints File",
            filetypes=filetypes
        )
        
        if filename:
            self.input_file_path.set(filename)
            self.load_input_file()
            
    def browse_output_file(self):
        """Browse for output file location."""
        filetypes = [
            ("GeoPackage", "*.gpkg"),
            ("Shapefile", "*.shp"),
            ("GeoJSON", "*.geojson"),
            ("All Files", "*.*")
        ]
        
        filename = filedialog.asksaveasfilename(
            title="Save Regularized Buildings As",
            filetypes=filetypes,
            defaultextension=".gpkg"
        )
        
        if filename:
            self.output_file_path.set(filename)
            
    def load_input_file(self):
        """Load and validate the input geospatial file."""
        file_path = self.input_file_path.get()
        if not file_path or not os.path.exists(file_path):
            return
            
        try:
            self.log_message("Loading input file...")
            self.buildings_gdf = gpd.read_file(file_path)
            
            # Validate geometry
            polygon_count = len(self.buildings_gdf[self.buildings_gdf.geometry.geom_type.isin(['Polygon', 'MultiPolygon'])])
            
            info_text = (f"Loaded: {len(self.buildings_gdf)} features "
                        f"({polygon_count} polygons, "
                        f"CRS: {self.buildings_gdf.crs})")
            
            self.file_info_label.config(text=info_text, foreground="green")
            self.log_message(f"Successfully loaded {file_path}")
            self.log_message(info_text)
            
            # Auto-generate output filename
            if not self.output_file_path.get():
                input_path = Path(file_path)
                output_path = input_path.parent / f"{input_path.stem}_regularized{input_path.suffix}"
                self.output_file_path.set(str(output_path))
                
        except Exception as e:
            error_msg = f"Error loading file: {str(e)}"
            self.file_info_label.config(text=error_msg, foreground="red")
            self.log_message(f"ERROR: {error_msg}")
            messagebox.showerror("File Load Error", error_msg)
            
    def get_parameters(self) -> Dict[str, Any]:
        """Get current parameter values."""
        return {
            'parallel_threshold': self.parallel_threshold.get(),
            'simplify': self.simplify_enabled.get(),
            'simplify_tolerance': self.simplify_tolerance.get(),
            'allow_45_degree': self.allow_45_degree.get(),
            'diagonal_threshold_reduction': self.diagonal_threshold_reduction.get(),
            'allow_circles': self.allow_circles.get(),
            'circle_threshold': self.circle_threshold.get(),
            'num_cores': self.num_cores.get(),
            'include_metadata': self.include_metadata.get(),
            'neighbor_alignment': self.neighbor_alignment.get(),
            'neighbor_search_distance': self.neighbor_search_distance.get(),
            'neighbor_max_rotation': self.neighbor_max_rotation.get(),
        }
        
    def start_processing(self):
        """Start the building regularization process in a separate thread."""
        if self.buildings_gdf is None:
            messagebox.showwarning("No Data", "Please load a building footprints file first.")
            return
            
        if self.processing:
            return
            
        # Start processing in separate thread
        self.processing = True
        self.process_button.config(state="disabled")
        self.progress.start()
        
        thread = threading.Thread(target=self.process_buildings)
        thread.daemon = True
        thread.start()
        
    def process_buildings(self):
        """Process buildings in background thread."""
        try:
            params = self.get_parameters()
            self.log_message("Starting regularization process...")
            self.log_message(f"Parameters: {params}")
            
            # Call the regularization function
            self.regularized_gdf = regularize_geodataframe(
                self.buildings_gdf,
                **params
            )
            
            # Update UI on main thread
            self.root.after(0, self.processing_complete)
            
        except Exception as e:
            error_msg = f"Processing error: {str(e)}"
            self.log_message(f"ERROR: {error_msg}")
            self.root.after(0, lambda: self.processing_error(error_msg))
            
    def processing_complete(self):
        """Handle successful processing completion."""
        self.processing = False
        self.progress.stop()
        self.process_button.config(state="normal")
        self.preview_button.config(state="normal")
        self.save_button.config(state="normal")
        
        success_msg = f"Regularization completed successfully! Processed {len(self.regularized_gdf)} buildings."
        self.log_message(success_msg)
        messagebox.showinfo("Success", success_msg)
        
    def processing_error(self, error_msg):
        """Handle processing errors."""
        self.processing = False
        self.progress.stop()
        self.process_button.config(state="normal")
        messagebox.showerror("Processing Error", error_msg)
        
    def preview_results(self):
        """Open a preview window showing before/after comparison."""
        if self.buildings_gdf is None or self.regularized_gdf is None:
            return
            
        try:
            PreviewWindow(self.root, self.buildings_gdf, self.regularized_gdf)
        except Exception as e:
            messagebox.showerror("Preview Error", f"Could not create preview: {str(e)}")
            
    def save_results(self):
        """Save the regularized results to file."""
        if self.regularized_gdf is None:
            messagebox.showwarning("No Results", "No regularized data to save. Please process buildings first.")
            return
            
        output_path = self.output_file_path.get()
        if not output_path:
            messagebox.showwarning("No Output Path", "Please specify an output file path.")
            return
            
        try:
            self.log_message(f"Saving results to {output_path}...")
            self.regularized_gdf.to_file(output_path)
            self.log_message("Results saved successfully!")
            messagebox.showinfo("Save Complete", f"Results saved to:\n{output_path}")
        except Exception as e:
            error_msg = f"Error saving file: {str(e)}"
            self.log_message(f"ERROR: {error_msg}")
            messagebox.showerror("Save Error", error_msg)
            
    def log_message(self, message):
        """Add a message to the status log."""
        self.status_text.config(state="normal")
        self.status_text.insert(tk.END, f"{message}\n")
        self.status_text.see(tk.END)
        self.status_text.config(state="disabled")
        self.root.update_idletasks()
        
    def load_default_settings(self):
        """Load default parameter settings."""
        self.log_message("Building Regulariser GUI started")
        self.log_message("Ready to load building footprints...")
        
    def save_settings(self):
        """Save current parameter settings to file."""
        settings = self.get_parameters()
        settings['input_file'] = self.input_file_path.get()
        settings['output_file'] = self.output_file_path.get()
        
        filename = filedialog.asksaveasfilename(
            title="Save Settings",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    json.dump(settings, f, indent=2)
                self.log_message(f"Settings saved to {filename}")
            except Exception as e:
                messagebox.showerror("Save Error", f"Could not save settings: {str(e)}")
                
    def load_settings(self):
        """Load parameter settings from file."""
        filename = filedialog.askopenfilename(
            title="Load Settings",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'r') as f:
                    settings = json.load(f)
                    
                # Update UI with loaded settings
                for key, value in settings.items():
                    if hasattr(self, key) and hasattr(getattr(self, key), 'set'):
                        getattr(self, key).set(value)
                        
                self.log_message(f"Settings loaded from {filename}")
            except Exception as e:
                messagebox.showerror("Load Error", f"Could not load settings: {str(e)}")
                
    def show_about(self):
        """Show about dialog."""
        about_text = """Building Regulariser GUI v1.0

A standalone application for cleaning and regularising building footprints in geospatial data.

Based on the DPIRD-DMA Building Regulariser library.

Features:
• Align edges to principal directions
• Convert near-rectangular buildings to perfect rectangles
• Convert near-circular buildings to perfect circles
• Simplify complex polygons
• Neighbor alignment support
• Parallel processing

For more information, visit:
https://github.com/DPIRD-DMA/Building-Regulariser
"""
        messagebox.showinfo("About Building Regulariser", about_text)


class PreviewWindow:
    """Preview window for comparing before/after results."""
    
    def __init__(self, parent, original_gdf, regularized_gdf):
        self.window = tk.Toplevel(parent)
        self.window.title("Preview - Before & After")
        self.window.geometry("1000x600")
        
        # Create matplotlib figure
        self.fig = Figure(figsize=(12, 6))
        
        # Plot original data
        ax1 = self.fig.add_subplot(121)
        original_gdf.plot(ax=ax1, color='lightblue', edgecolor='blue', alpha=0.7)
        ax1.set_title(f'Original Buildings ({len(original_gdf)} features)')
        ax1.set_aspect('equal')
        
        # Plot regularized data
        ax2 = self.fig.add_subplot(122)
        regularized_gdf.plot(ax=ax2, color='lightgreen', edgecolor='green', alpha=0.7)
        ax2.set_title(f'Regularized Buildings ({len(regularized_gdf)} features)')
        ax2.set_aspect('equal')
        
        self.fig.tight_layout()
        
        # Create canvas
        self.canvas = FigureCanvasTkAgg(self.fig, self.window)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        
        # Add close button
        ttk.Button(self.window, text="Close", command=self.window.destroy).pack(pady=10)


def main():
    """Main application entry point."""
    try:
        # Configure tkinter styling
        root = tk.Tk()
        style = ttk.Style()
        
        # Try to use a modern theme
        try:
            style.theme_use('clam')  # More modern looking theme
        except:
            pass  # Fall back to default theme
            
        # Create and run the application
        app = BuildingRegulariserGUI(root)
        
        # Center window on screen
        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        root.geometry(f'{width}x{height}+{x}+{y}')
        
        root.mainloop()
        
    except KeyboardInterrupt:
        print("\nApplication interrupted by user")
    except Exception as e:
        print(f"Unexpected error: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    main()