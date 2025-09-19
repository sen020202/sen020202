import os
import shapefile
import geopandas as gpd
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

def read_shp_metadata(shp_path):
    """Extract metadata from a shapefile, handle errors gracefully."""
    metadata = {
        "GeometryType": None,
        "Fields": [],
        "CRS": None,
        "Sidecars": {}
    }
    try:
        # Geometry type & fields
        sf = shapefile.Reader(shp_path)
        metadata["GeometryType"] = sf.shapeTypeName
        metadata["Fields"] = [
            {"Name": f[0], "Type": f[1], "Size": f[2], "Decimal": f[3]}
            for f in sf.fields[1:]
        ]
        sf.close()
    except Exception as e:
        metadata["Error"] = f"Error reading shapefile: {e}"
        return metadata

    try:
        # CRS (with geopandas)
        gdf = gpd.read_file(shp_path)
        metadata["CRS"] = str(gdf.crs) if gdf.crs else "None"
        del gdf  # free memory
    except Exception as e:
        metadata["CRS"] = f"Error reading CRS: {e}"

    try:
        # Sidecar files
        base = os.path.splitext(shp_path)[0]
        metadata["Sidecars"] = {
            "shx": os.path.exists(base + ".shx"),
            "dbf": os.path.exists(base + ".dbf"),
            "prj": os.path.exists(base + ".prj")
        }
    except Exception as e:
        metadata["Sidecars"] = {"Error": str(e)}

    return metadata


def compare_metadata(raw_meta, upd_meta):
    """Compare metadata and return issues found."""
    issues = []
    affected = False

    # Geometry type
    if raw_meta.get("GeometryType") != upd_meta.get("GeometryType"):
        issues.append(
            f"Geometry type mismatch: RAW={raw_meta.get('GeometryType')}, "
            f"UPDATED={upd_meta.get('GeometryType')}"
        )
        affected = True

    # CRS
    if raw_meta.get("CRS") != upd_meta.get("CRS"):
        issues.append(
            f"CRS mismatch: RAW={raw_meta.get('CRS')}, "
            f"UPDATED={upd_meta.get('CRS')}"
        )
        affected = True

    # Fields
    if len(raw_meta.get("Fields", [])) != len(upd_meta.get("Fields", [])):
        issues.append("Field count mismatch")
        affected = True
    else:
        for r, u in zip(raw_meta.get("Fields", []), upd_meta.get("Fields", [])):
            if r != u:
                issues.append(f"Field mismatch: RAW={r}, UPDATED={u}")
                affected = True

    # Sidecars
    for sidecar in ["shx", "dbf", "prj"]:
        if raw_meta["Sidecars"].get(sidecar) != upd_meta["Sidecars"].get(sidecar):
            issues.append(
                f"Sidecar mismatch for {sidecar.upper()}: "
                f"RAW={raw_meta['Sidecars'].get(sidecar)}, "
                f"UPDATED={upd_meta['Sidecars'].get(sidecar)}"
            )
            affected = True

    if not issues:
        issues = ["NO CHANGES"]

    return affected, issues


def compare_folders(raw_folder, upd_folder, report_path, progress_var, status_label):
    """Main comparison with progress updates."""
    try:
        raw_files = {f for f in os.listdir(raw_folder) if f.endswith(".shp")}
        upd_files = {f for f in os.listdir(upd_folder) if f.endswith(".shp")}
        all_files = sorted(raw_files.intersection(upd_files))

        total = len(all_files)
        if total == 0:
            messagebox.showwarning("Warning", "No matching .shp files found!")
            status_label.config(text="No matching files found", fg="red")
            return

        summary = []
        with pd.ExcelWriter(report_path, engine="openpyxl") as writer:
            for i, shp_file in enumerate(all_files, start=1):
                raw_path = os.path.join(raw_folder, shp_file)
                upd_path = os.path.join(upd_folder, shp_file)

                raw_meta = read_shp_metadata(raw_path)
                upd_meta = read_shp_metadata(upd_path)

                affected, issues = compare_metadata(raw_meta, upd_meta)
                summary.append({
                    "File": shp_file,
                    "Status": "AFFECTED" if affected else "NO ISSUES",
                    "Description": "; ".join(issues)
                })

                pd.DataFrame(issues, columns=["Description"]).to_excel(
                    writer, sheet_name=os.path.splitext(shp_file)[0][:30], index=False
                )

                # Update progress
                progress_var.set(int((i / total) * 100))
                root.update_idletasks()

            # Write summary
            pd.DataFrame(summary).to_excel(writer, sheet_name="SUMMARY", index=False)

            # Summary info with metadata
            summary_info = []
            for shp_file in all_files:
                raw_meta = read_shp_metadata(os.path.join(raw_folder, shp_file))
                upd_meta = read_shp_metadata(os.path.join(upd_folder, shp_file))
                summary_info.append({
                    "File": shp_file,
                    "RAW Geometry": raw_meta["GeometryType"],
                    "UPDATED Geometry": upd_meta["GeometryType"],
                    "RAW CRS": raw_meta["CRS"],
                    "UPDATED CRS": upd_meta["CRS"],
                    "RAW Sidecars": ", ".join([k for k, v in raw_meta["Sidecars"].items() if v]),
                    "UPDATED Sidecars": ", ".join([k for k, v in upd_meta["Sidecars"].items() if v])
                })
            pd.DataFrame(summary_info).to_excel(writer, sheet_name="SUMMARY_INFO", index=False)

        status_label.config(text="Comparison completed successfully!", fg="green")
        messagebox.showinfo("Success", f"Report generated at:\n{report_path}")

    except Exception as e:
        status_label.config(text=f"Error: {e}", fg="red")
        messagebox.showerror("Error", str(e))


def run_comparison():
    raw_folder = raw_entry.get().strip()
    upd_folder = upd_entry.get().strip()
    report_path = report_entry.get().strip()

    if not raw_folder or not upd_folder or not report_path:
        messagebox.showwarning("Input Error", "Please provide all inputs.")
        return

    progress_var.set(0)
    status_label.config(text="Running comparison...", fg="black")
    root.update_idletasks()
    compare_folders(raw_folder, upd_folder, report_path, progress_var, status_label)


def cancel_app():
    root.destroy()


# ---------------- GUI ----------------
root = tk.Tk()
root.title("SHP Metadata Comparator")
root.geometry("400x450")
root.configure(bg="#f0f4f7")

style = ttk.Style()
style.configure("TButton", font=("Arial", 9), padding=5)
style.configure("TLabel", background="#f0f4f7", font=("Arial", 10))

tk.Label(root, text="RAW Folder:").pack(pady=5)
raw_entry = tk.Entry(root, width=45)
raw_entry.pack()
tk.Button(root, text="Browse", command=lambda: raw_entry.insert(0, filedialog.askdirectory())).pack()

tk.Label(root, text="Updated Folder:").pack(pady=5)
upd_entry = tk.Entry(root, width=45)
upd_entry.pack()
tk.Button(root, text="Browse", command=lambda: upd_entry.insert(0, filedialog.askdirectory())).pack()

tk.Label(root, text="Report XLS Path:").pack(pady=5)
report_entry = tk.Entry(root, width=45)
report_entry.pack()
tk.Button(root, text="Browse", command=lambda: report_entry.insert(0, filedialog.asksaveasfilename(defaultextension=".xlsx"))).pack()

# Progress bar
progress_var = tk.IntVar()
progress = ttk.Progressbar(root, variable=progress_var, maximum=100, length=300)
progress.pack(pady=15)

# Run + Cancel buttons side by side
btn_frame = tk.Frame(root, bg="#f0f4f7")
btn_frame.pack(pady=10)
tk.Button(btn_frame, text="Run Comparison", command=run_comparison, bg="#4caf50", fg="white").grid(row=0, column=0, padx=10)
tk.Button(btn_frame, text="Cancel", command=cancel_app, bg="#f44336", fg="white").grid(row=0, column=1, padx=10)

# Status label
status_label = tk.Label(root, text="", font=("Arial", 10, "bold"))
status_label.pack(pady=10)

root.mainloop()
