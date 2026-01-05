#!/usr/bin/env python3
"""
LiDAR Classification Tool — Full GUI (progress bars removed from main tabs)

Changes in this version:
 - Removed embedded progressbars from Tab1/Tab2/Tab3 main UI.
 - Removed all updates to those removed widgets.
 - ProcessStatusWindow remains as the single place to show progress/messages.
 - Stop buttons kept in tabs for convenience (they call self._stop()).
"""
from pathlib import Path
import sys
import os
import time
import traceback
import threading
import queue
import tempfile
import shutil

# optional heavy libs
try:
    import laspy
    import numpy as np
    LASPY_AVAILABLE = True
except Exception:
    laspy = None
    np = None
    LASPY_AVAILABLE = False

# optional PIL for icon handling
try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except Exception:
    Image = None
    ImageTk = None
    PIL_AVAILABLE = False

# GUI libs
try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox, simpledialog
    TK_AVAILABLE = True
except Exception:
    tk = None
    ttk = None
    filedialog = None
    messagebox = None
    simpledialog = None
    TK_AVAILABLE = False

APP_TITLE = "LiDAR Classification Tool"
SUBTITLE = "Height from Ground | By Class"
ERROR_LOG = Path("merged_tool_error.log")

# New user colors
PALETTE_BG = "#D8D5CD"   # base background
PALETTE_ACC = "#B2BEB5"  # accent / buttons
PALETTE_HDR = "#C4C3D0"  # header / subtle contrast

# --- logging helpers
def safe_log_to_file(msg: str) -> None:
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(ERROR_LOG, "a", encoding="utf8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {msg}\n")
    except Exception:
        pass

def global_excepthook(exc_type, exc, tb):
    txt = "".join(traceback.format_exception(exc_type, exc, tb))
    safe_log_to_file("UNHANDLED EXCEPTION:\n" + txt)

sys.excepthook = global_excepthook

# --- small parsing helpers
def parse_from_list(s: str):
    s = (s or "").strip()
    if s == "" or s == "-1":
        return None
    parts = [p.strip() for p in s.split(",") if p.strip() != ""]
    return set(int(p) for p in parts)

def parse_mapping_line(line: str):
    if "->" not in line:
        raise ValueError("Invalid mapping: missing '->'")
    left, right = line.split("->", 1)
    left = left.strip()
    right = right.strip()
    from_set = parse_from_list(left)
    to_int = int(right)
    return (from_set, to_int, f"{left} -> {to_int}", left)

# --- minimal CSV mapping load/save
def load_mappings_csv_path(path: Path):
    mappings = []
    try:
        import csv as _csv
        def _is_intlike(s: str) -> bool:
            s = (s or "").strip()
            if s == "":
                return False
            return s.lstrip("+-").isdigit()
        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = _csv.reader(fh)
            first_row = True
            for row in reader:
                if not row:
                    continue
                fr = (row[0] if len(row) > 0 else "").strip()
                to = (row[1] if len(row) > 1 else "").strip()
                comment = (row[2] if len(row) > 2 else "").strip()
                if first_row:
                    if fr.lower() == "from" and to.lower() == "to":
                        first_row = False
                        continue
                    first_row = False
                if fr == "" and to == "":
                    continue
                if not _is_intlike(to):
                    continue
                from_set = parse_from_list(fr)
                to_int = int(to)
                mappings.append((from_set, to_int, f"{fr} -> {to_int}", fr, comment))
    except Exception:
        raise
    return mappings

def save_mappings_csv_path(path: Path, mappings):
    try:
        import csv as _csv
        with open(path, "w", encoding="utf8", newline="") as fh:
            writer = _csv.writer(fh)
            writer.writerow(["from", "to", "comment"])
            for (from_set, to_int, text_repr, from_text, comment) in mappings:
                writer.writerow([from_text, to_int, comment or ""])
    except Exception:
        raise

# --- disk helpers
def _safe_target_with_suffix(path: Path, suffix: str) -> Path:
    if not path.exists():
        return path
    return path.with_name(path.stem + suffix + path.suffix)

# --- core processing functions
def reclassify_folder(in_folder: Path, out_folder: Path, mappings, overwrite=False, suffix="_reclass",
                      other_mode=False, other_target=None, other_preserve=None,
                      progress_callback=None, log_callback=None, stop_event=None):
    if not LASPY_AVAILABLE:
        raise RuntimeError("laspy and numpy required")
    files = sorted(list(in_folder.rglob("*.las")) + list(in_folder.rglob("*.laz")))
    total = len(files)
    if total == 0:
        if log_callback:
            log_callback("No .las/.laz files found.")
        return 0
    processed = 0
    for fp in files:
        if stop_event is not None and stop_event.is_set():
            if log_callback:
                log_callback(f"Stopped before {fp}")
            break
        try:
            if log_callback:
                log_callback(f"Reading {fp}")
            las = laspy.read(str(fp))
            try:
                cls = np.asarray(las.classification)
            except Exception:
                cls = np.zeros(len(las.x), dtype=np.uint8)
            if other_mode:
                if other_target is None:
                    if log_callback:
                        log_callback("Other-mode enabled but no target class specified; skipping file")
                else:
                    if other_preserve is None:
                        mask = (cls != int(other_target))
                    else:
                        if len(other_preserve) == 0:
                            mask = np.ones_like(cls, dtype=bool)
                        else:
                            mask = ~np.isin(cls, list(other_preserve))
                    if mask.any():
                        cls[mask] = int(other_target)
                        if log_callback:
                            log_callback(f" - Other-mode: {mask.sum()} points moved to {other_target}")
                    else:
                        if log_callback:
                            log_callback(" - Other-mode: 0 points matched")
            else:
                for (from_set, to_int, text_repr, from_text, comment) in mappings:
                    if from_set is None:
                        mask = np.ones_like(cls, dtype=bool)
                    else:
                        mask = np.zeros_like(cls, dtype=bool)
                        for c in from_set:
                            mask |= (cls == c)
                    if mask.any():
                        cls[mask] = to_int
                        if log_callback:
                            log_callback(f" - {text_repr}: {mask.sum()} -> {to_int}")
                    else:
                        if log_callback:
                            log_callback(f" - {text_repr}: 0 points matched")
            if overwrite:
                out_fp = fp
            else:
                rel = fp.relative_to(in_folder)
                out_fp = out_folder / rel
                out_fp.parent.mkdir(parents=True, exist_ok=True)
                if out_fp.exists():
                    out_fp = _safe_target_with_suffix(out_fp, suffix)
            try:
                las.classification = cls.astype(las.classification.dtype if hasattr(las, "classification") else np.uint8)
            except Exception:
                las.classification = cls
            las.write(str(out_fp))
            if log_callback:
                log_callback(f"Written: {out_fp}")
        except Exception as e:
            safe_log_to_file(f"Reclassify error {fp}: {e}\n" + traceback.format_exc())
            if log_callback:
                log_callback(f"Error processing {fp}: {e}")
        processed += 1
        if progress_callback and total:
            try:
                progress_callback(int((processed / total) * 100))
            except Exception:
                pass
    if log_callback:
        log_callback("Reclassify complete.")
    return len(files)

def process_height_batch(in_folder: Path, out_folder: Path, veg_ranges, from_classes, ground_classes,
                         use_virtual_triangle=True, ground_method='tin_interp', tin_max_edge=None, tin_buffer=None,
                         overwrite=False, progress_callback=None, log_callback=None, stop_event=None):
    if not LASPY_AVAILABLE:
        raise RuntimeError("laspy and numpy required")
    files = sorted(list(in_folder.rglob("*.las")) + list(in_folder.rglob("*.laz")))
    total = len(files)
    if total == 0:
        if log_callback:
            log_callback("No .las/.laz files found.")
        return 0
    processed = 0
    for fp in files:
        if stop_event is not None and stop_event.is_set():
            if log_callback:
                log_callback(f"Stopped before {fp}")
            break
        try:
            if log_callback:
                log_callback(f"Height: reading {fp}")
            las = laspy.read(str(fp))
            x = np.asarray(las.x)
            y = np.asarray(las.y)
            z = np.asarray(las.z)
            N = len(z)
            try:
                classifications = np.asarray(las.classification)
            except Exception:
                classifications = np.zeros(N, dtype=np.uint8)
            ground_set = set(int(c) for c in ground_classes)
            ground_mask = np.isin(classifications, list(ground_set))
            from_set = set(int(c) for c in from_classes)
            candidate_mask = (~ground_mask) & np.isin(classifications, list(from_set))
            candidate_idx = np.nonzero(candidate_mask)[0]
            if np.any(ground_mask):
                try:
                    from scipy.spatial import cKDTree
                    ground_xy = np.column_stack((x[ground_mask], y[ground_mask]))
                    ground_z = z[ground_mask]
                    tree = cKDTree(ground_xy)
                    pts_xy = np.column_stack((x[candidate_idx], y[candidate_idx]))
                    _, idx = tree.query(pts_xy, k=1)
                    est = ground_z[idx]
                except Exception:
                    est = np.full(len(candidate_idx), float(np.min(z)), dtype=float)
            else:
                est = np.full(len(candidate_idx), float(np.min(z)), dtype=float)
            heights = z[candidate_idx] - est
            out_class = classifications.copy()
            eps = 1e-3
            for vr in veg_ranges:
                vmin = vr.get('min', None)
                vmax = vr.get('max', None)
                vclass = int(vr.get('class', 0))
                if vmin is None:
                    mask_min = np.ones_like(heights, dtype=bool)
                else:
                    mask_min = heights >= (vmin - eps)
                if vmax is None:
                    mask_max = np.ones_like(heights, dtype=bool)
                else:
                    mask_max = heights <= (vmax + eps)
                sel = mask_min & mask_max
                if not np.any(sel):
                    continue
                sel_idx = candidate_idx[sel]
                prev_same = (out_class[sel_idx] == vclass)
                to_set = sel_idx[~prev_same]
                out_class[to_set] = vclass
            if overwrite:
                out_fp = fp
            else:
                rel = fp.relative_to(in_folder)
                out_fp = out_folder / rel
                out_fp.parent.mkdir(parents=True, exist_ok=True)
                if out_fp.exists():
                    out_fp = _safe_target_with_suffix(out_fp, "_height")
            try:
                las.classification = out_class.astype(las.classification.dtype if hasattr(las, "classification") else np.uint8)
            except Exception:
                las.classification = out_class
            las.write(str(out_fp))
            if log_callback:
                log_callback(f"Height written: {out_fp}")
        except Exception as e:
            safe_log_to_file(f"Height error {fp}: {e}\n" + traceback.format_exc())
            if log_callback:
                log_callback(f"Height error {fp}: {e}")
        processed += 1
        if progress_callback and total:
            try:
                progress_callback(int((processed / total) * 100))
            except Exception:
                pass
    if log_callback:
        log_callback("Height processing complete.")
    return processed

# --- GUI
if TK_AVAILABLE:
    class AddMappingDialog(tk.Toplevel):
        """Custom Add/Edit mapping dialog that shows Hexagon icon in header and validates input."""
        def __init__(self, master, initial_text=""):
            super().__init__(master)
            self.title("Add mapping")
            self.transient(master)
            self.resizable(False, False)
            self.result = None
            self.protocol("WM_DELETE_WINDOW", self._on_cancel)

            # Header w/ hex icon (if available)
            hdr = tk.Frame(self, bg=PALETTE_BG, padx=6, pady=6)
            hdr.pack(fill="x")
            try:
                if getattr(master, "hex_header_img", None) is not None:
                    img_lbl = tk.Label(hdr, image=master.hex_header_img, bg=PALETTE_BG)
                    img_lbl.image = master.hex_header_img
                    img_lbl.pack(side="left", padx=(0,8))
            except Exception:
                pass
            tk.Label(hdr, text="Enter mapping like '2 -> 1' or '2,8 -> 1' or '-1 -> 1'", bg=PALETTE_BG).pack(side="left", anchor="w")

            body = tk.Frame(self, padx=8, pady=6)
            body.pack(fill="both", expand=True)
            self.var = tk.StringVar(value=initial_text)
            self.entry = ttk.Entry(body, textvariable=self.var, width=44)
            self.entry.pack(fill="x", pady=(0,8))
            btns = tk.Frame(body)
            btns.pack(fill="x")
            ttk.Button(btns, text="OK", command=self._on_ok).pack(side="left", padx=4)
            ttk.Button(btns, text="Cancel", command=self._on_cancel).pack(side="left", padx=4)
            self.entry.focus_set()
            self.grab_set()
            self.wait_window(self)

        def _on_ok(self):
            txt = self.var.get().strip()
            if not txt:
                messagebox.showerror("Invalid", "Mapping string cannot be empty", parent=self)
                return
            try:
                parse_mapping_line(txt)  # validate
            except Exception as e:
                messagebox.showerror("Invalid mapping", str(e), parent=self)
                return
            self.result = txt
            self.destroy()

        def _on_cancel(self):
            self.result = None
            self.destroy()

    class ProcessStatusWindow(tk.Toplevel):
        """Process status window — shows hexagon icon (if available) + single-line message + progressbar."""
        def __init__(self, master):
            super().__init__(master)
            self.title("Process Status")
            self.resizable(False, False)
            self.transient(master)
            self.protocol("WM_DELETE_WINDOW", lambda: None)
            self.geometry("520x110")
            try:
                self.configure(bg=PALETTE_BG)
            except Exception:
                pass

            top_row = tk.Frame(self, bg=PALETTE_BG)
            top_row.pack(fill="x", padx=8, pady=(8,0))
            try:
                if getattr(master, 'hex_header_img', None) is not None:
                    img_lbl = tk.Label(top_row, image=master.hex_header_img, bg=PALETTE_BG)
                    img_lbl.image = master.hex_header_img
                    img_lbl.pack(side="left", padx=(0,6))
            except Exception:
                pass
            lbl = tk.Label(top_row, text="Status:", font=("TkDefaultFont", 10, "bold"), bg=PALETTE_BG)
            lbl.pack(side="left", anchor="w")

            self.msg_var = tk.StringVar(value="Starting...")
            self.msg_lbl = tk.Label(self, textvariable=self.msg_var, anchor="w", bg=PALETTE_BG)
            self.msg_lbl.pack(fill="x", padx=8, pady=(4,4))

            try:
                style = ttk.Style(self)
                style_name = "Hexagon.Horizontal.TProgressbar"
                style.configure(style_name, troughcolor=PALETTE_BG)
                self.progress = ttk.Progressbar(self, length=480, mode="determinate", style=style_name)
            except Exception:
                self.progress = ttk.Progressbar(self, length=480, mode="determinate")
            self.progress.pack(fill="x", padx=8, pady=(0,8))

        def set_text(self, text: str):
            try:
                s = " ".join(str(text).splitlines())
                self.msg_var.set(s.strip()[:180])
            except Exception:
                pass

        def set_progress(self, pct: float):
            try:
                self.progress["value"] = float(pct)
            except Exception:
                pass

        def close_now(self, delay_ms: int = 300):
            try:
                self.after(delay_ms, self.destroy)
            except Exception:
                pass

    class MergedApp(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(APP_TITLE)
            self.minsize(700, 420)
            try:
                self.configure(bg=PALETTE_BG)
            except Exception:
                pass
            self.queue = queue.Queue()
            self._stop_event = threading.Event()
            self.worker = None
            self.status_win = None

            # load hex images
            self.hex_img = None
            self.hex_header_img = None
            self._load_hexagon_image()

            try:
                self._style = ttk.Style(self)
                self._style.configure("Accent.TButton", background=PALETTE_ACC, foreground="black")
                self._style.configure("Hexagon.Horizontal.TProgressbar", troughcolor=PALETTE_BG)
            except Exception:
                self._style = None

            self._build_ui()
            self.after(120, self._process_queue)
            self.protocol("WM_DELETE_WINDOW", self._on_close)

        def _load_hexagon_image(self):
            script_dir = Path(__file__).parent if "__file__" in globals() else Path.cwd()
            candidates = [
                Path("/mnt/data/Hexagon.png"),
                Path("/mnt/data/Hexagon.gif"),
                Path("/mnt/data/Hexagon.ico"),
                script_dir / "Hexagon.png",
                script_dir / "Hexagon.gif",
                script_dir / "Hexagon.ico",
            ]
            found = None
            for p in candidates:
                if p.exists():
                    found = p
                    break
            try:
                if found and found.suffix.lower() == '.ico':
                    if sys.platform.startswith('win'):
                        try:
                            self.iconbitmap(str(found))
                        except Exception:
                            pass
                img_path = None
                if found:
                    if found.suffix.lower() in ('.png', '.gif'):
                        img_path = found
                    elif found.suffix.lower() == '.ico' and PIL_AVAILABLE:
                        img_path = found
                if img_path is not None:
                    if PIL_AVAILABLE:
                        try:
                            base = Image.open(str(img_path))
                            header_img = base.convert('RGBA').resize((48, 48), Image.LANCZOS)
                            btn_img = base.convert('RGBA').resize((20, 20), Image.LANCZOS)
                            self.hex_header_img = ImageTk.PhotoImage(header_img)
                            self.hex_img = ImageTk.PhotoImage(btn_img)
                        except Exception:
                            try:
                                if img_path.suffix.lower() in ('.png', '.gif'):
                                    self.hex_img = tk.PhotoImage(file=str(img_path))
                                    self.hex_header_img = self.hex_img
                            except Exception:
                                self.hex_img = None
                                self.hex_header_img = None
                    else:
                        if img_path.suffix.lower() in ('.png', '.gif'):
                            try:
                                self.hex_img = tk.PhotoImage(file=str(img_path))
                                self.hex_header_img = self.hex_img
                            except Exception:
                                self.hex_img = None
                                self.hex_header_img = None
                else:
                    self.hex_img = None
                    self.hex_header_img = None
            except Exception:
                self.hex_img = None
                self.hex_header_img = None

        def _make_btn(self, parent, text, command, width=None, use_icon=True):
            """
            Create a button. If use_icon==True and hex icon available, include it; otherwise a text-only button.
            We will call with use_icon=False for bottom controls.
            """
            try:
                if use_icon and getattr(self, "hex_img", None) is not None:
                    btn = ttk.Button(parent, text=text, command=command, image=self.hex_img, compound="left", style="Accent.TButton")
                    if width:
                        try:
                            btn.configure(width=width)
                        except Exception:
                            pass
                    return btn
            except Exception:
                pass
            try:
                btn = ttk.Button(parent, text=text, command=command, style="Accent.TButton")
                if width:
                    try:
                        btn.configure(width=width)
                    except Exception:
                        pass
                return btn
            except Exception:
                try:
                    return tk.Button(parent, text=text, command=command, width=width or 0)
                except Exception:
                    raise

        def _build_ui(self):
            top = tk.Frame(self, bg=PALETTE_HDR, padx=6, pady=6)
            top.pack(fill="x")

            left = tk.Frame(top, bg=PALETTE_ACC)
            right = tk.Frame(top, bg=PALETTE_HDR)
            left.pack(side="left", fill="both", expand=True)
            right.pack(side="left", fill="both", expand=True)

            title_frame = tk.Frame(left, bg=PALETTE_ACC)
            title_frame.pack(fill="both", expand=True, padx=(4,8), pady=4)

            icon_container = tk.Frame(title_frame, bg=PALETTE_HDR, width=48, height=48)
            icon_container.pack_propagate(False)
            icon_container.pack(side="left", padx=(0,8))
            if getattr(self, 'hex_header_img', None) is not None:
                img_lbl = tk.Label(icon_container, image=self.hex_header_img, bg=PALETTE_HDR)
                img_lbl.image = self.hex_header_img
                img_lbl.pack(expand=True)
            else:
                tk.Label(icon_container, text="", bg=PALETTE_HDR).pack(expand=True)

            title_lbl = tk.Label(title_frame, text=APP_TITLE, font=("TkDefaultFont", 11, "bold"), bg=PALETTE_ACC)
            title_lbl.pack(anchor="w")
            sub_lbl = tk.Label(title_frame, text=SUBTITLE, font=("TkDefaultFont", 9), bg=PALETTE_ACC)
            sub_lbl.pack(anchor="w")

            nb = ttk.Notebook(self)
            nb.pack(fill="both", expand=True, padx=6, pady=6)

            self.tab1 = ttk.Frame(nb)
            nb.add(self.tab1, text="By class")
            self._build_tab1(self.tab1)

            self.tab2 = ttk.Frame(nb)
            nb.add(self.tab2, text="Height from ground")
            self._build_tab2(self.tab2)

            self.tab3 = ttk.Frame(nb)
            nb.add(self.tab3, text="Combined")
            self._build_tab3(self.tab3)

        # TAB1
        def _build_tab1(self, parent):
            frm = ttk.Frame(parent, padding=6)
            frm.pack(fill="both", expand=True)
            r = 0
            ttk.Label(frm, text="Input folder:").grid(row=r, column=0, sticky="w")
            self.t1_input = tk.StringVar()
            self.t1_in_entry = ttk.Entry(frm, textvariable=self.t1_input, width=36)
            self.t1_in_entry.grid(row=r, column=1, sticky="w")
            self.t1_in_browse = self._make_btn(frm, "Browse", lambda: self._browse(self.t1_input), use_icon=False)
            self.t1_in_browse.grid(row=r, column=2)

            r += 1
            ttk.Label(frm, text="Output folder:").grid(row=r, column=0, sticky="w")
            self.t1_output = tk.StringVar()
            self.t1_out_entry = ttk.Entry(frm, textvariable=self.t1_output, width=36)
            self.t1_out_entry.grid(row=r, column=1, sticky="w")
            self.t1_out_browse = self._make_btn(frm, "Browse", lambda: self._browse(self.t1_output), use_icon=False)
            self.t1_out_browse.grid(row=r, column=2)

            r += 1
            self.t1_classify_label = ttk.Label(frm, text="Classify (top → bottom):")
            self.t1_classify_label.grid(row=r, column=0, sticky="nw")
            self.t1_listbox = tk.Listbox(frm, height=6, width=36)
            self.t1_listbox.grid(row=r, column=1, sticky="w")
            bfrm = ttk.Frame(frm)
            bfrm.grid(row=r, column=2, sticky="n")
            # Small control buttons: remove icons here (use_icon=False)
            self.t1_add_btn = self._make_btn(bfrm, "Add", self.t1_add, use_icon=False)
            self.t1_add_btn.grid(row=0, column=0, pady=2)
            self.t1_edit_btn = self._make_btn(bfrm, "Edit", self.t1_edit, use_icon=False)
            self.t1_edit_btn.grid(row=1, column=0, pady=2)
            self.t1_remove_btn = self._make_btn(bfrm, "Remove", self.t1_remove, use_icon=False)
            self.t1_remove_btn.grid(row=2, column=0, pady=2)
            self.t1_load_btn = self._make_btn(bfrm, "Load CSV", self.t1_load_csv, use_icon=False)
            self.t1_load_btn.grid(row=3, column=0, pady=2)
            self.t1_save_btn = self._make_btn(bfrm, "Save CSV", self.t1_save_csv, use_icon=False)
            self.t1_save_btn.grid(row=4, column=0, pady=2)

            r += 1
            self.t1_other_mode = tk.BooleanVar(value=False)
            self.t1_other_cb = ttk.Checkbutton(frm, text="Other than listed classes -> move to target class",
                                               variable=self.t1_other_mode, command=self._toggle_t1_other_mode)
            self.t1_other_cb.grid(row=r, column=1, sticky="w")

            r += 1
            ttk.Label(frm, text="Target class (move remaining classes into):").grid(row=r, column=0, sticky="w")
            self.t1_other_target = tk.StringVar(value="0")
            ttk.Entry(frm, textvariable=self.t1_other_target, width=8).grid(row=r, column=1, sticky="w")

            r += 1
            self.t1_preserve_label = ttk.Label(frm, text="Preserve classes (comma-separated) — classes NOT moved:")
            self.t1_preserve_var = tk.StringVar(value="")
            self.t1_preserve_entry = ttk.Entry(frm, textvariable=self.t1_preserve_var, width=24)
            self.t1_preserve_label.grid(row=r, column=0, sticky="w")
            self.t1_preserve_entry.grid(row=r, column=1, sticky="w")
            self.t1_preserve_label.grid_remove()
            self.t1_preserve_entry.grid_remove()

            r += 1
            self.t1_overwrite = tk.BooleanVar(value=False)
            self.t1_overwrite_cb = ttk.Checkbutton(frm, text="File Overwrite (write in-place)", variable=self.t1_overwrite, command=self._toggle_t1_overwrite)
            self.t1_overwrite_cb.grid(row=r, column=1, sticky="w")

            r += 1
            ttk.Label(frm, text="Output suffix:").grid(row=r, column=0, sticky="w")
            self.t1_suffix = tk.StringVar(value="_reclass")
            ttk.Entry(frm, textvariable=self.t1_suffix, width=12).grid(row=r, column=1, sticky="w")

            r += 1
            f = ttk.Frame(frm)
            f.grid(row=r, column=0, columnspan=3, pady=6)
            # Start/Stop bottom buttons: remove icons (use_icon=False)
            ttk.Button(f, text="Start (By class)", command=self.t1_start).grid(row=0, column=0, padx=6)
            ttk.Button(f, text="Stop", command=self._stop).grid(row=0, column=1, padx=6)

        def _toggle_t1_overwrite(self):
            if self.t1_overwrite.get():
                try:
                    self.t1_out_entry.grid_remove()
                except Exception:
                    pass
                try:
                    self.t1_out_browse.grid_remove()
                except Exception:
                    pass
                self.t1_output.set("")
            else:
                try:
                    self.t1_out_entry.grid()
                except Exception:
                    pass
                try:
                    self.t1_out_browse.grid()
                except Exception:
                    pass

        def _toggle_t1_other_mode(self):
            other_on = bool(self.t1_other_mode.get())
            try:
                if other_on:
                    try:
                        self.t1_classify_label.grid_remove()
                        self.t1_listbox.grid_remove()
                        self.t1_add_btn.grid_remove()
                        self.t1_edit_btn.grid_remove()
                        self.t1_remove_btn.grid_remove()
                        self.t1_load_btn.grid_remove()
                        self.t1_save_btn.grid_remove()
                    except Exception:
                        pass
                    try:
                        self.t1_preserve_label.grid()
                        self.t1_preserve_entry.grid()
                    except Exception:
                        pass
                else:
                    try:
                        self.t1_classify_label.grid()
                        self.t1_listbox.grid()
                        self.t1_add_btn.grid()
                        self.t1_edit_btn.grid()
                        self.t1_remove_btn.grid()
                        self.t1_load_btn.grid()
                        self.t1_save_btn.grid()
                    except Exception:
                        pass
                    try:
                        self.t1_preserve_label.grid_remove()
                        self.t1_preserve_entry.grid_remove()
                    except Exception:
                        pass
            except Exception:
                pass

        # TAB2
        def _build_tab2(self, parent):
            frm = ttk.Frame(parent, padding=6)
            frm.pack(fill="both", expand=True)
            r = 0
            ttk.Label(frm, text="Input folder:").grid(row=r, column=0, sticky="w")
            self.t2_input = tk.StringVar()
            self.t2_in_entry = ttk.Entry(frm, textvariable=self.t2_input, width=36)
            self.t2_in_entry.grid(row=r, column=1, sticky="w")
            self.t2_in_browse = self._make_btn(frm, "Browse", lambda: self._browse(self.t2_input), use_icon=False)
            self.t2_in_browse.grid(row=r, column=2)

            r += 1
            ttk.Label(frm, text="Output folder:").grid(row=r, column=0, sticky="w")
            self.t2_output = tk.StringVar()
            self.t2_out_entry = ttk.Entry(frm, textvariable=self.t2_output, width=36)
            self.t2_out_entry.grid(row=r, column=1, sticky="w")
            self.t2_out_browse = self._make_btn(frm, "Browse", lambda: self._browse(self.t2_output), use_icon=False)
            self.t2_out_browse.grid(row=r, column=2)

            r += 1
            veg_lab = ttk.Label(frm, text="Vegetation ranges (min,max,class) — add rows below")
            veg_lab.grid(row=r, column=0, columnspan=3, sticky="w")
            self.t2_ranges = []
            defaults = [(0.0,2.0,3),(2.0,10.0,4),(10.0,None,5)]
            for d in defaults:
                self._t2_add_range(frm, d[0], d[1], d[2])

            r += 4
            # bottom Add Range button—icon removed
            ttk.Button(frm, text="Add Range", command=lambda: self._t2_add_range(frm, None, None, None)).grid(row=r, column=0, sticky="w")

            r += 1
            ttk.Label(frm, text="From class codes:").grid(row=r, column=0, sticky="w")
            self.t2_from_classes = tk.StringVar(value="")
            ttk.Entry(frm, textvariable=self.t2_from_classes, width=24).grid(row=r, column=1, sticky="w")

            r += 1
            ttk.Label(frm, text="Ground class codes:").grid(row=r, column=0, sticky="w")
            self.t2_ground_classes = tk.StringVar(value="2")
            ttk.Entry(frm, textvariable=self.t2_ground_classes, width=24).grid(row=r, column=1, sticky="w")

            r += 1
            ttk.Label(frm, text="TIN buffer (m):").grid(row=r, column=0, sticky="w")
            self.t2_tin_buffer = tk.StringVar(value="0.0")
            ttk.Entry(frm, textvariable=self.t2_tin_buffer, width=12).grid(row=r, column=1, sticky="w")

            r += 1
            self.t2_overwrite = tk.BooleanVar(value=False)
            self.t2_overwrite_cb = ttk.Checkbutton(frm, text="File Overwrite (write in-place)", variable=self.t2_overwrite, command=self._toggle_t2_overwrite)
            self.t2_overwrite_cb.grid(row=r, column=1, sticky="w")

            r += 1
            f = ttk.Frame(frm)
            f.grid(row=r, column=0, columnspan=3, pady=6)
            # Start/Stop without icons
            ttk.Button(f, text="Start (Height)", command=self.t2_start).grid(row=0, column=0, padx=6)
            ttk.Button(f, text="Stop", command=self._stop).grid(row=0, column=1, padx=6)

        def _t2_add_range(self, parent, vmin="", vmax="", vclass=""):
            row_index = len(self.t2_ranges) + 2
            min_var = tk.StringVar(value=str(vmin) if vmin is not None else "")
            max_var = tk.StringVar(value=str(vmax) if vmax is not None else "")
            cls_var = tk.StringVar(value=str(vclass) if vclass is not None else "")
            e_min = ttk.Entry(parent, textvariable=min_var, width=8)
            e_max = ttk.Entry(parent, textvariable=max_var, width=8)
            e_cls = ttk.Entry(parent, textvariable=cls_var, width=8)
            e_min.grid(row=row_index, column=0, sticky="w")
            e_max.grid(row=row_index, column=1, sticky="w")
            e_cls.grid(row=row_index, column=2, sticky="w")
            self.t2_ranges.append((min_var, max_var, cls_var, e_min, e_max, e_cls))

        def _toggle_t2_overwrite(self):
            if self.t2_overwrite.get():
                try:
                    self.t2_out_entry.grid_remove()
                except Exception:
                    pass
                try:
                    self.t2_out_browse.grid_remove()
                except Exception:
                    pass
                self.t2_output.set("")
            else:
                try:
                    self.t2_out_entry.grid()
                except Exception:
                    pass
                try:
                    self.t2_out_browse.grid()
                except Exception:
                    pass

        # TAB3
        def _build_tab3(self, parent):
            frm = ttk.Frame(parent, padding=6)
            frm.pack(fill="both", expand=True)
            r = 0
            ttk.Label(frm, text="Input folder:").grid(row=r, column=0, sticky="w")
            self.t3_input = tk.StringVar()
            self.t3_in_entry = ttk.Entry(frm, textvariable=self.t3_input, width=40)
            self.t3_in_entry.grid(row=r, column=1, sticky="w")
            self.t3_in_browse = self._make_btn(frm, "Browse", lambda: self._browse(self.t3_input), use_icon=False)
            self.t3_in_browse.grid(row=r, column=2)

            r += 1
            ttk.Label(frm, text="Output folder:").grid(row=r, column=0, sticky="w")
            self.t3_output = tk.StringVar()
            self.t3_out_entry = ttk.Entry(frm, textvariable=self.t3_output, width=40)
            self.t3_out_entry.grid(row=r, column=1, sticky="w")
            self.t3_out_browse = self._make_btn(frm, "Browse", lambda: self._browse(self.t3_output), use_icon=False)
            self.t3_out_browse.grid(row=r, column=2)

            r += 1
            ttk.Button(frm, text="Use settings from Tab 1 & 2", command=self.t3_sync_settings).grid(row=r, column=0, sticky="w")

            r += 1
            self.t3_overwrite = tk.BooleanVar(value=False)
            self.t3_overwrite_cb = ttk.Checkbutton(frm, text="File Overwrite (write in-place)", variable=self.t3_overwrite, command=self._toggle_t3_overwrite)
            self.t3_overwrite_cb.grid(row=r, column=1, sticky="w")

            r += 1
            f = ttk.Frame(frm)
            f.grid(row=r, column=0, columnspan=3, pady=6)
            ttk.Button(f, text="Start (Combined)", command=self.t3_start).grid(row=0, column=0, padx=6)
            ttk.Button(f, text="Stop", command=self._stop).grid(row=0, column=1, padx=6)

        def _toggle_t3_overwrite(self):
            if self.t3_overwrite.get():
                try:
                    self.t3_out_entry.grid_remove()
                except Exception:
                    pass
                try:
                    self.t3_out_browse.grid_remove()
                except Exception:
                    pass
                self.t3_output.set("")
            else:
                try:
                    self.t3_out_entry.grid()
                except Exception:
                    pass
                try:
                    self.t3_out_browse.grid()
                except Exception:
                    pass

        # helpers
        def _browse(self, var: tk.StringVar):
            d = filedialog.askdirectory()
            if d:
                var.set(d)

        def _open_log(self):
            try:
                if not ERROR_LOG.exists():
                    messagebox.showinfo("Logs", f"Log file not found: {ERROR_LOG}")
                    return
                if sys.platform.startswith("win"):
                    os.startfile(str(ERROR_LOG))
                elif sys.platform.startswith("darwin"):
                    os.system(f"open \"{str(ERROR_LOG)}\"")
                else:
                    os.system(f"xdg-open \"{str(ERROR_LOG)}\"")
            except Exception as e:
                messagebox.showerror("Open log", str(e))

        def _log_and_send(self, msg: str):
            safe_log_to_file(msg)
            try:
                if self.status_win and getattr(self.status_win, "winfo_exists", lambda: False)():
                    self.status_win.set_text(msg)
            except Exception:
                pass

        # mapping ops — uses AddMappingDialog for Add/Edit
        def t1_add(self):
            dlg = AddMappingDialog(self, "")
            if dlg.result is None:
                return
            d = dlg.result
            try:
                m = parse_mapping_line(d)
                if not hasattr(self, "t1_mappings"):
                    self.t1_mappings = []
                self.t1_mappings.append((m[0], m[1], m[2], m[3], ""))
                self.t1_listbox.insert(tk.END, m[2])
            except Exception as e:
                messagebox.showerror("Invalid mapping", str(e))

        def t1_edit(self):
            sel = self.t1_listbox.curselection()
            if not sel:
                messagebox.showinfo("Edit", "Select a mapping to edit")
                return
            idx = sel[0]
            current = self.t1_mappings[idx][3]
            dlg = AddMappingDialog(self, initial_text=current)
            if dlg.result is None:
                return
            d = dlg.result
            try:
                m = parse_mapping_line(d)
                self.t1_mappings[idx] = (m[0], m[1], m[2], m[3], self.t1_mappings[idx][4])
                self.t1_listbox.delete(idx)
                self.t1_listbox.insert(idx, m[2])
            except Exception as e:
                messagebox.showerror("Invalid mapping", str(e))

        def t1_remove(self):
            sel = self.t1_listbox.curselection()
            if not sel:
                return
            idx = sel[0]
            del self.t1_mappings[idx]
            self.t1_listbox.delete(idx)

        def t1_load_csv(self):
            p = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
            if not p:
                return
            try:
                new = load_mappings_csv_path(Path(p))
                self.t1_mappings = []
                try:
                    self.t1_listbox.config(state="normal")
                except Exception:
                    pass
                self.t1_listbox.delete(0, tk.END)
                for m in new:
                    self.t1_mappings.append(m)
                    display = m[2] + (f"  // {m[4]}" if m[4] else "")
                    self.t1_listbox.insert(tk.END, display)
            except Exception as e:
                messagebox.showerror("Load CSV", str(e))

        def t1_save_csv(self):
            p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
            if not p:
                return
            try:
                mappings = getattr(self, "t1_mappings", [])
                save_mappings_csv_path(Path(p), mappings)
                messagebox.showinfo("Saved", f"Mappings saved to {p}")
            except Exception as e:
                messagebox.showerror("Save CSV", str(e))

        # start/stop orchestration
        def _start_worker(self, target_fn):
            if self.worker and self.worker.is_alive():
                messagebox.showinfo("Running", "Another job is running")
                return
            self._stop_event.clear()
            self.worker = threading.Thread(target=lambda: self._worker_runner(target_fn), daemon=True)
            self.worker.start()
            # open Process Status window (single source of progress)
            try:
                if self.status_win and getattr(self.status_win, "winfo_exists", lambda: False)():
                    self.status_win.set_text("Starting new job...")
                    self.status_win.set_progress(0)
                else:
                    self.status_win = ProcessStatusWindow(self)
                try:
                    self.status_win.lift()
                except Exception:
                    pass
            except Exception:
                pass

        def _worker_runner(self, target_fn):
            try:
                target_fn(self.queue, self._stop_event)
            except Exception as e:
                safe_log_to_file("Worker runner error: " + str(e) + "\n" + traceback.format_exc())
                self.queue.put(("generic_log", f"Worker error: {e}"))

        def _stop(self):
            if self.worker and self.worker.is_alive():
                self._stop_event.set()
                safe_log_to_file("Stop requested")
                try:
                    if self.status_win and getattr(self.status_win, "winfo_exists", lambda: False)():
                        self.status_win.set_text("Stop requested...")
                except Exception:
                    pass

        def _process_queue(self):
            try:
                while True:
                    typ, payload = self.queue.get_nowait()
                    if typ in ("t1_log", "t2_log", "t3_log", "generic_log"):
                        msg = str(payload)
                        self._log_and_send(msg)
                    elif typ in ("t1_progress", "t2_progress", "t3_progress"):
                        # only update the ProcessStatusWindow (no in-tab progressbars)
                        try:
                            v = float(payload)
                            if self.status_win and getattr(self.status_win, "winfo_exists", lambda: False)():
                                self.status_win.set_progress(v)
                        except Exception:
                            pass
                    elif typ in ("t1_done", "t2_done", "t3_done"):
                        try:
                            self._log_and_send(str(payload or "Process completed successfully."))
                            if self.status_win and getattr(self.status_win, "winfo_exists", lambda: False)():
                                self.status_win.set_progress(100)
                                self.status_win.close_now(delay_ms=700)
                                self.status_win = None
                        except Exception:
                            pass
                        try:
                            messagebox.showinfo("Process Status", payload or "Process completed successfully.")
                        except Exception:
                            pass
                    self.queue.task_done()
            except queue.Empty:
                pass
            finally:
                self.after(150, self._process_queue)

        # Tab start functions (unchanged logic)
        def t1_start(self):
            in_folder = self.t1_input.get().strip()
            out_folder = self.t1_output.get().strip()
            if not in_folder:
                messagebox.showerror("Missing", "Select input folder for Tab1")
                return
            mappings = getattr(self, "t1_mappings", [])
            other_flag = bool(self.t1_other_mode.get())
            try:
                other_target_val = int(self.t1_other_target.get()) if self.t1_other_target.get().strip() != "" else None
            except Exception:
                messagebox.showerror("Invalid", "Invalid target class for Other-than-listed")
                return

            other_preserve_set = None
            if other_flag:
                txt = self.t1_preserve_var.get().strip()
                if txt == "":
                    messagebox.showerror("Missing", "Enter comma-separated preserve classes (classes NOT moved) when Other-mode is ON")
                    return
                try:
                    other_preserve_set = set(int(x.strip()) for x in txt.split(",") if x.strip() != "")
                except Exception:
                    messagebox.showerror("Invalid", "Preserve classes invalid (use comma-separated integers)")
                    return
                if other_target_val is None:
                    messagebox.showerror("Missing", "Specify target class to move remaining classes into")
                    return
            overwrite_flag = bool(self.t1_overwrite.get())
            target_out = Path(in_folder) if overwrite_flag else Path(out_folder or in_folder)
            suffix = self.t1_suffix.get() or "_reclass"

            def worker(q, stop_event):
                def logcb(m): q.put(("t1_log", m))
                def progcb(p): q.put(("t1_progress", p))
                try:
                    reclassify_folder(Path(in_folder), Path(target_out), list(mappings), overwrite=overwrite_flag, suffix=suffix,
                                      other_mode=other_flag, other_target=other_target_val, other_preserve=other_preserve_set,
                                      progress_callback=progcb, log_callback=logcb, stop_event=stop_event)
                    q.put(("t1_done", "Process completed successfully."))
                except Exception as e:
                    logcb("Fatal: " + str(e))
            self._start_worker(worker)

        def t2_start(self):
            in_folder = self.t2_input.get().strip()
            out_folder = self.t2_output.get().strip()
            if not in_folder:
                messagebox.showerror("Missing", "Select input folder for Tab2")
                return
            if not out_folder and not self.t2_overwrite.get():
                messagebox.showerror("Missing", "Select output folder or enable File Overwrite")
                return
            veg_ranges = []
            for (min_var, max_var, cls_var, *_rest) in self.t2_ranges:
                try:
                    vmin = float(min_var.get()) if min_var.get().strip() != "" else None
                except Exception:
                    messagebox.showerror("Invalid", f"Invalid min: {min_var.get()}")
                    return
                try:
                    vmax = float(max_var.get()) if max_var.get().strip() != "" else None
                except Exception:
                    messagebox.showerror("Invalid", f"Invalid max: {max_var.get()}")
                    return
                try:
                    vcls = int(cls_var.get()) if cls_var.get().strip() != "" else 0
                except Exception:
                    messagebox.showerror("Invalid", f"Invalid class: {cls_var.get()}")
                    return
                veg_ranges.append({"min": vmin, "max": vmax, "class": vcls})
            try:
                from_classes = [int(x.strip()) for x in self.t2_from_classes.get().split(",") if x.strip() != ""]
            except Exception:
                messagebox.showerror("Invalid", "From class codes invalid")
                return
            try:
                ground_classes = [int(x.strip()) for x in self.t2_ground_classes.get().split(",") if x.strip() != ""]
                if not ground_classes:
                    ground_classes = [2]
            except Exception:
                ground_classes = [2]
            try:
                tin_buffer_val = float(self.t2_tin_buffer.get()) if self.t2_tin_buffer.get().strip() != "" else None
            except Exception:
                tin_buffer_val = None

            overwrite_flag = bool(self.t2_overwrite.get())
            target_out = Path(in_folder) if overwrite_flag else Path(out_folder or in_folder)

            def worker(q, stop_event):
                def logcb(m): q.put(("t2_log", m))
                def progcb(p): q.put(("t2_progress", p))
                try:
                    process_height_batch(Path(in_folder), Path(target_out), veg_ranges, from_classes, ground_classes,
                                         True, "tin_interp", None, tin_buffer_val,
                                         overwrite=overwrite_flag, progress_callback=progcb, log_callback=logcb, stop_event=stop_event)
                    q.put(("t2_done", "Process completed successfully."))
                except Exception as e:
                    logcb("Fatal: " + str(e))
            self._start_worker(worker)

        def t3_sync_settings(self):
            self.t3_input.set(self.t1_input.get() or self.t2_input.get())
            if not self.t1_overwrite.get() and not self.t2_overwrite.get():
                self.t3_output.set(self.t1_output.get() or self.t2_output.get())
            else:
                self.t3_output.set("")
            self._log_and_send("Settings synced from Tab1/Tab2")

        def t3_start(self):
            in_folder = self.t3_input.get().strip()
            out_folder = self.t3_output.get().strip()
            if not in_folder:
                messagebox.showerror("Missing", "Select input for Combined run")
                return
            if not self.t3_overwrite.get() and not out_folder:
                messagebox.showerror("Missing", "Select output folder or enable File Overwrite for Combined run")
                return
            mappings = getattr(self, "t1_mappings", [])
            veg_ranges = []
            for (min_var, max_var, cls_var, *_rest) in self.t2_ranges:
                try:
                    vmin = float(min_var.get()) if min_var.get().strip() != "" else None
                    vmax = float(max_var.get()) if max_var.get().strip() != "" else None
                    vcls = int(cls_var.get()) if cls_var.get().strip() != "" else 0
                except Exception:
                    messagebox.showerror("Invalid", "Invalid vegetation ranges")
                    return
                veg_ranges.append({"min": vmin, "max": vmax, "class": vcls})
            try:
                from_classes = [int(x.strip()) for x in self.t2_from_classes.get().split(",") if x.strip() != ""]
            except Exception:
                messagebox.showerror("Invalid", "From class codes invalid")
                return
            try:
                ground_classes = [int(x.strip()) for x in self.t2_ground_classes.get().split(",") if x.strip() != ""]
                if not ground_classes:
                    ground_classes = [2]
            except Exception:
                ground_classes = [2]
            combined_overwrite = bool(self.t3_overwrite.get())

            tmpdir = tempfile.mkdtemp(prefix="merged_tmp_")
            run_log = Path(tmpdir) / "combined_run.log"
            safe_log_to_file(f"Combined run log: {run_log}")

            def combined_worker(q, stop_event):
                def logcb(m):
                    try:
                        with open(run_log, "a", encoding="utf8") as fh:
                            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {m}\n")
                    except Exception:
                        pass
                    safe_log_to_file(m)
                    q.put(("t3_log", m))
                try:
                    logcb("Combined: Starting by-class step...")
                    if combined_overwrite:
                        reclassify_folder(Path(in_folder), Path(in_folder), mappings, overwrite=True, suffix="_reclass", progress_callback=lambda p: q.put(("t3_progress", int(p*0.5))), log_callback=logcb, stop_event=stop_event)
                        if stop_event.is_set():
                            logcb("Combined stopped after reclass")
                            return
                        logcb("Combined: Starting height (in-place)...")
                        process_height_batch(Path(in_folder), Path(in_folder), veg_ranges, from_classes, ground_classes, True, "tin_interp", None, None, overwrite=True, progress_callback=lambda p: q.put(("t3_progress", 50 + int(p*0.5))), log_callback=logcb, stop_event=stop_event)
                    else:
                        reclassify_folder(Path(in_folder), Path(tmpdir), mappings, overwrite=False, suffix="_reclass", progress_callback=lambda p: q.put(("t3_progress", int(p*0.5))), log_callback=logcb, stop_event=stop_event)
                        if stop_event.is_set():
                            logcb("Combined stopped after reclass")
                            return
                        logcb("Combined: Starting height step...")
                        process_height_batch(Path(tmpdir), Path(out_folder), veg_ranges, from_classes, ground_classes, True, "tin_interp", None, None, overwrite=False, progress_callback=lambda p: q.put(("t3_progress", 50 + int(p*0.5))), log_callback=logcb, stop_event=stop_event)
                    logcb("Combined finished both steps")
                    q.put(("t3_done", "Process completed successfully."))
                except Exception as e:
                    safe_log_to_file("Combined error: " + str(e) + "\n" + traceback.format_exc())
                    q.put(("t3_log", f"Combined fatal: {e}"))
                finally:
                    try:
                        shutil.rmtree(tmpdir, ignore_errors=True)
                        q.put(("t3_log", f"Removed tmp dir: {tmpdir}"))
                    except Exception:
                        pass

            self._start_worker(combined_worker)

        def _on_close(self):
            if self.worker and self.worker.is_alive():
                if not messagebox.askyesno("Quit", "A job is running. Quit anyway?"):
                    return
                self._stop_event.set()
                time.sleep(0.2)
            self.destroy()

    def main():
        try:
            app = MergedApp()
            app.geometry("700x480")
            app.mainloop()
        except Exception:
            safe_log_to_file("Fatal GUI error:\n" + traceback.format_exc())
            raise

    if __name__ == "__main__":
        if not LASPY_AVAILABLE:
            print("Warning: laspy/numpy not available. GUI will run but processing requires laspy.")
        main()

else:
    def cli_help():
        print("Tkinter not available. This script requires a GUI environment.")

    if __name__ == "__main__":
        cli_help()
