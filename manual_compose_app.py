"""
Manual image compositing GUI: pick background/object folders, navigate with arrows,
click to place object and save to output folder.
"""

from __future__ import annotations

import json
import os
import random
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from compose_images import (
    crop_and_resize_to_target,
    composite_images,
    create_labelme_json,
    resize_object_with_height,
)


def list_backgrounds(folder: str) -> list[str]:
    exts = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    )


def list_objects(folder: str) -> list[str]:
    if not folder or not os.path.isdir(folder):
        return []
    return sorted(
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith(".png")
    )


def _folder_basename(path: str) -> str:
    p = (path or "").strip().rstrip("/\\")
    return os.path.basename(p) if p else ""


def _safe_prefix_token(s: str) -> str:
    """Safe fragment for filenames / save prefix."""
    if not s:
        return "item"
    t = re.sub(r"[^\w\-.]+", "_", s, flags=re.UNICODE)
    t = t.strip("._")
    return t or "item"


def _label_from_object_folder_path(path: str) -> str:
    """Default Labelme label = object folder name (minimal escaping for JSON)."""
    name = _folder_basename(path)
    name = name.replace('"', "").replace("\n", "").replace("\r", "")
    return name.strip() or "object"


STATE_FILENAME = ".manual_compose_state.json"


def _state_file_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), STATE_FILENAME)


def _normalize_folder_size_basename(name: str) -> str:
    """Normalize unicode dashes to ASCII hyphen for parsing."""
    s = (name or "").strip()
    for ch in ("\u2212", "\u2013", "\u2014", "\u2010"):  # minus, en, em, hyphen
        s = s.replace(ch, "-")
    return s


def _parse_object_height_rule_from_folder_basename(name: str):
    """
    Map output folder *basename* to a height predicate.

    Folder name means **min_height-max_height** (inclusive on both ends when both given):

    - ``-30`` or ``0-30``  → only max: ``0 <= height <= 30``
    - ``30-50`` → ``30 <= height <= 50``
    - ``300-`` → only min: ``height >= 300``

    Parsing uses a **single split on the first hyphen** so ``-30`` is not mistaken for
    ``30`` + suffix patterns, and ``300-`` is not confused with a two-number range.

    Returns a callable ``height -> bool`` or None if the name does not match any rule.
    """
    raw = _normalize_folder_size_basename(name)
    if "-" not in raw:
        return None
    left, right = raw.split("-", 1)
    left = left.strip()
    right = right.strip()

    # "-30" / "0-30" style: implicit min 0, max = right
    if left == "" and right.isdigit():
        hi = int(right)
        return lambda h, hi=hi: 0 <= h <= hi

    # "300-" style: min = left, no max
    if right == "" and left.isdigit():
        lo = int(left)
        return lambda h, lo=lo: h >= lo

    # "30-50" style: both bounds
    if left.isdigit() and right.isdigit():
        lo, hi = int(left), int(right)
        if lo > hi:
            lo, hi = hi, lo
        return lambda h, lo=lo, hi=hi: lo <= h <= hi

    return None


def count_labeled_results_in_folder(folder: str) -> int:
    """Count image files that have a same-stem .json (one composite result)."""
    if not folder or not os.path.isdir(folder):
        return 0
    img_exts = {".jpg", ".jpeg", ".png"}
    n = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    for f in names:
        base, ext = os.path.splitext(f)
        if ext.lower() not in img_exts:
            continue
        json_path = os.path.join(folder, base + ".json")
        if os.path.isfile(json_path):
            n += 1
    return n


class ManualComposeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Manual compose — background + object")
        self.minsize(900, 700)

        self.bg_folder = tk.StringVar()
        self.obj_folder = tk.StringVar()
        self.out_folder = tk.StringVar()
        self.object_height = tk.IntVar(value=100)
        self.output_w = tk.IntVar(value=1280)
        self.output_h = tk.IntVar(value=720)
        self.save_prefix = tk.StringVar(value="")
        self.save_format = tk.StringVar(value="jpg")  # jpg or png
        self.random_obj_on_next_bg = tk.BooleanVar(value=False)
        self.random_rotate_object = tk.BooleanVar(value=False)
        self.labelme_label = tk.StringVar(value="")
        self.auto_output_by_object_size = tk.BooleanVar(value=False)

        self.bg_paths: list[str] = []
        self.obj_paths: list[str] = []
        self.bg_index = 0
        self.obj_index = 0

        self.bg_work: Image.Image | None = None  # RGB, output_w x output_h (updated after each place)
        self._photo: ImageTk.PhotoImage | None = None
        self._obj_photo_small: ImageTk.PhotoImage | None = None
        self._display_scale = 1.0
        self._offset_x = 0
        self._offset_y = 0
        self._disp_w = 0
        self._disp_h = 0

        # Each entry: (background RGB before placement, image path, json path)
        self._undo_stack: list[tuple[Image.Image, str, str]] = []

        self._output_folder_paths: list[str] = []
        self._spin_object_height: ttk.Spinbox | None = None

        self._build_ui()
        self._load_output_folders_state()
        self.object_height.trace_add("write", self._schedule_output_listbox_refresh_counts)

        self.bind_all("<Left>", self._on_arrow_left_background)
        self.bind_all("<Right>", self._on_arrow_right_background)
        self.bind_all("<Down>", self._on_all_arrow_down)
        self.bind_all("<Up>", self._on_all_arrow_up)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Defaults: label = object folder name; prefix = background folder + "_" + label
        self.bg_folder.trace_add("write", self._schedule_folder_derived_defaults)
        self.obj_folder.trace_add("write", self._schedule_folder_derived_defaults)
        self.labelme_label.trace_add("write", self._schedule_save_prefix_from_bg_and_label)

    def _schedule_output_listbox_refresh_counts(self, *_args) -> None:
        self.after_idle(self._refresh_output_listbox_with_counts)

    def _on_auto_output_toggle(self) -> None:
        self._refresh_output_listbox_with_counts()
        self._save_output_folders_state()

    def _schedule_folder_derived_defaults(self, *_args) -> None:
        self.after_idle(self._apply_folder_derived_defaults)

    def _schedule_save_prefix_from_bg_and_label(self, *_args) -> None:
        self.after_idle(self._sync_save_prefix_from_background_and_label)

    def _apply_folder_derived_defaults(self) -> None:
        obj = self.obj_folder.get().strip()
        if obj and os.path.isdir(obj):
            self.labelme_label.set(_label_from_object_folder_path(obj))
        self._sync_save_prefix_from_background_and_label()

    def _sync_save_prefix_from_background_and_label(self) -> None:
        bg = self.bg_folder.get().strip()
        if not bg or not os.path.isdir(bg):
            return
        lbl = self.labelme_label.get().strip() or "object"
        self.save_prefix.set(
            f"{_safe_prefix_token(_folder_basename(bg))}_{_safe_prefix_token(lbl)}"
        )

    def _focus_allows_background_left_right(self) -> bool:
        """Do not change background when typing in entries, spinboxes, listbox, etc."""
        try:
            w = self.focus_get()
        except tk.TclError:
            return True
        cls = w.winfo_class()
        if cls in ("Entry", "TEntry", "Text", "TSpinbox", "Spinbox", "Listbox", "TCombobox"):
            return False
        return True

    def _on_arrow_left_background(self, event: tk.Event) -> str | None:
        """Previous background on Left if not in a text field."""
        if not self._focus_allows_background_left_right():
            return None
        self.prev_background()
        return "break"

    def _on_arrow_right_background(self, event: tk.Event) -> str | None:
        """Next background on Right only if not in a text field."""
        if not self._focus_allows_background_left_right():
            return None
        self.next_background()
        return "break"

    def _focus_is_inside_object_height_spinbox(self) -> bool:
        """ttk.Spinbox often puts keyboard focus on an inner Entry; walk masters."""
        spin = self._spin_object_height
        if spin is None:
            return False
        try:
            w = self.focus_get()
        except tk.TclError:
            return False
        while w is not None:
            if w is spin:
                return True
            try:
                w = w.master
            except (tk.TclError, AttributeError):
                break
        return False

    def _on_all_arrow_down(self, _event: tk.Event) -> str | None:
        """Next object on Down; never change object-height spinbox value with arrows."""
        if self._focus_is_inside_object_height_spinbox():
            self.next_object()
            return "break"
        try:
            w = self.focus_get()
            cls = w.winfo_class()
        except tk.TclError:
            return None
        if cls in ("Entry", "TEntry", "Text", "Listbox"):
            return None
        if cls in ("TSpinbox", "Spinbox"):
            return None
        self.next_object()
        return "break"

    def _on_all_arrow_up(self, _event: tk.Event) -> str | None:
        """Previous object on Up; never change object-height spinbox value with arrows."""
        if self._focus_is_inside_object_height_spinbox():
            self.prev_object()
            return "break"
        try:
            w = self.focus_get()
            cls = w.winfo_class()
        except tk.TclError:
            return None
        if cls in ("Entry", "TEntry", "Text", "Listbox"):
            return None
        if cls in ("TSpinbox", "Spinbox"):
            return None
        self.prev_object()
        return "break"

    def _load_output_folders_state(self) -> None:
        path = _state_file_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return
        folders = data.get("output_folders") or data.get("folders") or []
        if not isinstance(folders, list):
            return
        self._output_folder_paths = [str(p) for p in folders if p and isinstance(p, str)]
        self.auto_output_by_object_size.set(
            bool(data.get("auto_output_by_object_size", False))
        )
        self.random_rotate_object.set(bool(data.get("random_rotate_object", False)))
        self._refresh_output_listbox_with_counts()
        sel = int(data.get("selected_output_index", 0))
        if self._output_folder_paths:
            sel = max(0, min(sel, len(self._output_folder_paths) - 1))
            self.out_listbox.selection_clear(0, tk.END)
            self.out_listbox.selection_set(sel)
            self.out_listbox.see(sel)
            self.out_folder.set(self._output_folder_paths[sel])

    def _save_output_folders_state(self) -> None:
        try:
            sel = self.out_listbox.curselection()
            idx = int(sel[0]) if sel else 0
        except (tk.TclError, IndexError, ValueError):
            idx = 0
        data = {
            "output_folders": self._output_folder_paths,
            "selected_output_index": idx,
            "auto_output_by_object_size": self.auto_output_by_object_size.get(),
            "random_rotate_object": self.random_rotate_object.get(),
        }
        try:
            with open(_state_file_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass

    def _refresh_output_listbox_with_counts(self) -> None:
        """Fill listbox with ``[count] path`` and optional auto-target marker."""
        prev_sel = ()
        try:
            prev_sel = self.out_listbox.curselection()
        except tk.TclError:
            pass
        prev_idx = int(prev_sel[0]) if prev_sel else None

        self.out_listbox.delete(0, tk.END)
        try:
            h = int(self.object_height.get())
        except (tk.TclError, ValueError):
            h = 0
        auto_target: str | None = None
        if self.auto_output_by_object_size.get():
            auto_target = self._resolve_output_folder_for_height(h)

        for p in self._output_folder_paths:
            cnt = count_labeled_results_in_folder(p)
            base = _folder_basename(p)
            rule = _parse_object_height_rule_from_folder_basename(base)
            star = "  ★" if auto_target and os.path.normpath(p) == os.path.normpath(auto_target) else ""
            miss = "  (no rule)" if self.auto_output_by_object_size.get() and rule is None else ""
            line = f"[{cnt:>4}]  {p}{star}{miss}"
            self.out_listbox.insert(tk.END, line)

        if prev_idx is not None and self._output_folder_paths:
            prev_idx = max(0, min(prev_idx, len(self._output_folder_paths) - 1))
            self.out_listbox.selection_clear(0, tk.END)
            self.out_listbox.selection_set(prev_idx)
            self.out_listbox.see(prev_idx)

    def _listbox_index_to_folder_path(self, index: int) -> str | None:
        if 0 <= index < len(self._output_folder_paths):
            return self._output_folder_paths[index]
        return None

    def _resolve_output_folder_for_height(self, height: int) -> str | None:
        """First list folder whose basename matches the height rule."""
        for p in self._output_folder_paths:
            base = _folder_basename(p)
            rule = _parse_object_height_rule_from_folder_basename(base)
            if rule is not None and rule(height):
                return p
        return None

    def _select_listbox_index_for_path(self, folder_path: str) -> None:
        norm = os.path.normpath(folder_path)
        for i, p in enumerate(self._output_folder_paths):
            if os.path.normpath(p) == norm:
                self.out_listbox.selection_clear(0, tk.END)
                self.out_listbox.selection_set(i)
                self.out_listbox.see(i)
                self.out_folder.set(p)
                return

    def _on_output_listbox_select(self, _event: tk.Event | None = None) -> None:
        sel = self.out_listbox.curselection()
        if not sel:
            return
        i = int(sel[0])
        p = self._listbox_index_to_folder_path(i)
        if p is not None:
            self.out_folder.set(p)
            self._save_output_folders_state()

    def add_output_folder(self) -> None:
        d = filedialog.askdirectory(title="Add output folder to list")
        if not d:
            return
        d = os.path.normpath(d)
        if d not in self._output_folder_paths:
            self._output_folder_paths.append(d)
            self._refresh_output_listbox_with_counts()
        idx = self._output_folder_paths.index(d)
        self.out_listbox.selection_clear(0, tk.END)
        self.out_listbox.selection_set(idx)
        self.out_listbox.see(idx)
        self.out_folder.set(d)
        self._save_output_folders_state()

    def remove_output_folder(self) -> None:
        sel = self.out_listbox.curselection()
        if not sel:
            messagebox.showinfo("Output folders", "Select a folder in the list to remove.")
            return
        i = int(sel[0])
        if 0 <= i < len(self._output_folder_paths):
            self._output_folder_paths.pop(i)
        self._refresh_output_listbox_with_counts()
        if self._output_folder_paths:
            new_i = min(i, len(self._output_folder_paths) - 1)
            self.out_listbox.selection_set(new_i)
            self.out_folder.set(self._output_folder_paths[new_i])
        else:
            self.out_folder.set("")
        self._save_output_folders_state()

    def _on_close(self) -> None:
        self._save_output_folders_state()
        self.destroy()

    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}

        frm = ttk.Frame(self, padding=8)
        frm.pack(fill=tk.BOTH, expand=True)

        # Row: folders
        row0 = ttk.Frame(frm)
        row0.pack(fill=tk.X, **pad)
        ttk.Button(row0, text="Background folder…", command=self.pick_bg_folder).pack(
            side=tk.LEFT, **pad
        )
        ttk.Entry(row0, textvariable=self.bg_folder, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True, **pad
        )

        row1 = ttk.Frame(frm)
        row1.pack(fill=tk.X, **pad)
        ttk.Button(row1, text="Object folder…", command=self.pick_obj_folder).pack(
            side=tk.LEFT, **pad
        )
        ttk.Entry(row1, textvariable=self.obj_folder, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True, **pad
        )

        row2 = ttk.Frame(frm)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="Output folders (select one):").pack(side=tk.LEFT, **pad)
        out_list_frame = ttk.Frame(row2)
        out_list_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, **pad)
        scroll = ttk.Scrollbar(out_list_frame)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.out_listbox = tk.Listbox(
            out_list_frame,
            height=4,
            selectmode=tk.SINGLE,
            yscrollcommand=scroll.set,
            exportselection=False,
        )
        self.out_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.config(command=self.out_listbox.yview)
        self.out_listbox.bind("<<ListboxSelect>>", self._on_output_listbox_select)

        row2b = ttk.Frame(frm)
        row2b.pack(fill=tk.X, **pad)
        ttk.Button(row2b, text="Add output folder…", command=self.add_output_folder).pack(
            side=tk.LEFT, **pad
        )
        ttk.Button(row2b, text="Remove selected", command=self.remove_output_folder).pack(
            side=tk.LEFT, **pad
        )
        ttk.Button(row2b, text="Refresh counts", command=self._refresh_output_listbox_with_counts).pack(
            side=tk.LEFT, **pad
        )
        ttk.Checkbutton(
            row2b,
            text="Auto folder by object height",
            variable=self.auto_output_by_object_size,
            command=self._on_auto_output_toggle,
        ).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Label(
            row2b,
            text="(basename: min-max — -30 ⇒ 0–30, 30-50 ⇒ 30–50, 300- ⇒ ≥300)",
            font=("TkDefaultFont", 8),
        ).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(row2b, text="Active path:").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Entry(row2b, textvariable=self.out_folder, width=55).pack(
            side=tk.LEFT, fill=tk.X, expand=True, **pad
        )

        # Row: height + output size
        row3 = ttk.Frame(frm)
        row3.pack(fill=tk.X, **pad)
        ttk.Label(row3, text="Object height (px):").pack(side=tk.LEFT, **pad)
        self._spin_object_height = ttk.Spinbox(
            row3, from_=1, to=2000, textvariable=self.object_height, width=8
        )
        self._spin_object_height.pack(side=tk.LEFT, **pad)
        ttk.Label(row3, text="Output W×H:").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Spinbox(row3, from_=320, to=4096, textvariable=self.output_w, width=6).pack(
            side=tk.LEFT, **pad
        )
        ttk.Label(row3, text="×").pack(side=tk.LEFT)
        ttk.Spinbox(row3, from_=240, to=4096, textvariable=self.output_h, width=6).pack(
            side=tk.LEFT, **pad
        )

        row4 = ttk.Frame(frm)
        row4.pack(fill=tk.X, **pad)
        ttk.Label(row4, text="Save prefix:").pack(side=tk.LEFT, **pad)
        ttk.Entry(row4, textvariable=self.save_prefix, width=20).pack(side=tk.LEFT, **pad)
        ttk.Label(row4, text="Format:").pack(side=tk.LEFT, padx=(12, 4))
        ttk.Radiobutton(row4, text="JPG", variable=self.save_format, value="jpg").pack(
            side=tk.LEFT
        )
        ttk.Radiobutton(row4, text="PNG", variable=self.save_format, value="png").pack(
            side=tk.LEFT
        )
        ttk.Label(row4, text="Labelme label:").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Entry(row4, textvariable=self.labelme_label, width=12).pack(side=tk.LEFT, **pad)

        # Navigation + random option
        row5 = ttk.Frame(frm)
        row5.pack(fill=tk.X, **pad)
        ttk.Button(row5, text="→ Next background", command=self.next_background).pack(
            side=tk.LEFT, **pad
        )
        ttk.Button(row5, text="↓ Next object", command=self.next_object).pack(
            side=tk.LEFT, **pad
        )
        ttk.Button(row5, text="Undo last (right-click image)", command=self.undo_last_placement).pack(
            side=tk.LEFT, **pad
        )
        ttk.Checkbutton(
            row5,
            text="Pick random object when moving to next background",
            variable=self.random_obj_on_next_bg,
        ).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Checkbutton(
            row5,
            text="Random rotation on place",
            variable=self.random_rotate_object,
            command=self._save_output_folders_state,
        ).pack(side=tk.LEFT, padx=(12, 0))

        self.status = tk.StringVar(value="Load folders, then click on the image to place object.")
        ttk.Label(frm, textvariable=self.status, wraplength=880).pack(fill=tk.X, **pad)

        # Main area: canvas + object preview
        main_row = ttk.Frame(frm)
        main_row.pack(fill=tk.BOTH, expand=True, **pad)
        main_row.columnconfigure(0, weight=1)
        main_row.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            main_row,
            bg="#222",
            highlightthickness=0,
            takefocus=True,
        )
        self.canvas.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        self.canvas.bind("<Button-3>", self._on_canvas_right_click_undo)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        preview_col = ttk.Frame(main_row, width=220)
        preview_col.grid(row=0, column=1, sticky=tk.NS)
        preview_col.grid_propagate(False)
        ttk.Label(preview_col, text="Current object").pack(anchor=tk.W, pady=(0, 4))
        self.obj_preview = tk.Label(
            preview_col,
            bg="#3a3a3a",
            fg="#aaa",
            text="No object",
            compound=tk.TOP,
            padx=8,
            pady=8,
        )
        self.obj_preview.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frm,
            text="Shortcuts: Right = next background · Left = previous background · Down = next object · "
            "Up = previous object · Right-click image = undo last save",
            font=("TkDefaultFont", 8),
        ).pack(anchor=tk.W)

    def pick_bg_folder(self) -> None:
        d = filedialog.askdirectory(title="Select background folder")
        if d:
            self.bg_folder.set(d)
            self.refresh_backgrounds()

    def pick_obj_folder(self) -> None:
        d = filedialog.askdirectory(title="Select object folder (PNG)")
        if d:
            self.obj_folder.set(d)
            self.refresh_objects()

    def refresh_backgrounds(self) -> None:
        self.bg_paths = list_backgrounds(self.bg_folder.get())
        self.bg_index = 0
        self.load_current_background()

    def refresh_objects(self) -> None:
        self.obj_paths = list_objects(self.obj_folder.get())
        self.obj_index = 0
        self.set_status()
        self.update_object_preview()

    def load_current_background(self) -> None:
        self._undo_stack.clear()
        if not self.bg_paths:
            self.bg_work = None
            self.redraw_canvas()
            self.set_status()
            return
        self.bg_index %= len(self.bg_paths)
        path = self.bg_paths[self.bg_index]
        try:
            im = Image.open(path)
            ow = int(self.output_w.get())
            oh = int(self.output_h.get())
            self.bg_work = crop_and_resize_to_target(im, ow, oh).convert("RGB")
        except OSError as e:
            messagebox.showerror("Error", f"Could not load background:\n{e}")
            self.bg_work = None
        self.redraw_canvas()
        self.set_status()

    def update_object_preview(self) -> None:
        """Show thumbnail of current object PNG (alpha on gray)."""
        if not self.obj_paths:
            self._obj_photo_small = None
            self.obj_preview.configure(image="", text="No object")
            return
        path = self.obj_paths[self.obj_index % len(self.obj_paths)]
        try:
            img = Image.open(path).convert("RGBA")
        except OSError:
            self._obj_photo_small = None
            self.obj_preview.configure(image="", text="Load error")
            return
        w, h = img.size
        thumb_max = 200
        scale = min(thumb_max / max(w, 1), thumb_max / max(h, 1), 1.0)
        if scale < 1.0:
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )
        bg = Image.new("RGB", img.size, (58, 58, 58))
        bg.paste(img, mask=img.split()[3])
        self._obj_photo_small = ImageTk.PhotoImage(bg)
        self.obj_preview.configure(image=self._obj_photo_small, text="")

    def next_background(self) -> None:
        if not self.bg_paths:
            messagebox.showinfo("Info", "No backgrounds loaded.")
            return
        self.bg_index = (self.bg_index + 1) % len(self.bg_paths)
        if self.random_obj_on_next_bg.get() and self.obj_paths:
            self.obj_index = random.randrange(len(self.obj_paths))
        self.load_current_background()
        self.update_object_preview()
        self._focus_canvas_for_shortcuts()

    def prev_background(self) -> None:
        if not self.bg_paths:
            return
        self.bg_index = (self.bg_index - 1) % len(self.bg_paths)
        self.load_current_background()
        self.update_object_preview()
        self._focus_canvas_for_shortcuts()

    def next_object(self) -> None:
        if not self.obj_paths:
            messagebox.showinfo("Info", "No objects loaded.")
            return
        self.obj_index = (self.obj_index + 1) % len(self.obj_paths)
        self.set_status()
        self.update_object_preview()
        self._focus_canvas_for_shortcuts()

    def prev_object(self) -> None:
        if not self.obj_paths:
            return
        self.obj_index = (self.obj_index - 1) % len(self.obj_paths)
        self.set_status()
        self.update_object_preview()
        self._focus_canvas_for_shortcuts()

    def set_status(self) -> None:
        parts = []
        if self.bg_paths:
            parts.append(
                f"BG {self.bg_index + 1}/{len(self.bg_paths)}: {os.path.basename(self.bg_paths[self.bg_index])}"
            )
        else:
            parts.append("No backgrounds")
        if self.obj_paths:
            parts.append(
                f"Object {self.obj_index + 1}/{len(self.obj_paths)}: {os.path.basename(self.obj_paths[self.obj_index])}"
            )
        else:
            parts.append("No objects")
        self.status.set(" · ".join(parts) + " — Left-click image to place and save.")

    def _on_canvas_configure(self, _event: tk.Event) -> None:
        self.redraw_canvas()

    def redraw_canvas(self) -> None:
        self.canvas.delete("all")
        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        if self.bg_work is None:
            self.canvas.create_text(
                cw // 2,
                ch // 2,
                text="Select background folder and load images",
                fill="white",
                font=("TkDefaultFont", 14),
            )
            return

        iw, ih = self.bg_work.size
        scale = min(cw / iw, ch / ih)
        self._display_scale = scale
        self._disp_w = int(iw * scale)
        self._disp_h = int(ih * scale)
        self._offset_x = (cw - self._disp_w) // 2
        self._offset_y = (ch - self._disp_h) // 2

        disp = self.bg_work.resize((self._disp_w, self._disp_h), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        self.canvas.create_image(self._offset_x, self._offset_y, anchor=tk.NW, image=self._photo)

    def _focus_canvas_for_shortcuts(self) -> None:
        """Move keyboard focus to the image canvas so Left/Right/Up/Down shortcuts work (not spinbox/entry)."""
        try:
            self.canvas.focus_set()
        except tk.TclError:
            pass

    def canvas_to_image_coords(self, cx: int, cy: int) -> tuple[int, int] | None:
        if self.bg_work is None:
            return None
        ix = (cx - self._offset_x) / self._display_scale
        iy = (cy - self._offset_y) / self._display_scale
        iw, ih = self.bg_work.size
        if ix < 0 or iy < 0 or ix >= iw or iy >= ih:
            return None
        return int(ix), int(iy)

    @staticmethod
    def clamp_center(cx: int, cy: int, obj_w: int, obj_h: int, iw: int, ih: int) -> tuple[int, int]:
        hw, hh = obj_w // 2, obj_h // 2
        cx = max(hw, min(iw - hw, cx))
        cy = max(hh, min(ih - hh, cy))
        return cx, cy

    def _on_canvas_right_click_undo(self, _event: tk.Event) -> str:
        """Erase last output (same as Undo button) — right mouse button on image area."""
        self._focus_canvas_for_shortcuts()
        self.undo_last_placement()
        return "break"

    def on_canvas_click(self, event: tk.Event) -> None:
        self._focus_canvas_for_shortcuts()
        target_h = int(self.object_height.get())
        target_h = max(1, min(2000, target_h))

        if self.auto_output_by_object_size.get():
            if not self._output_folder_paths:
                messagebox.showwarning(
                    "Output",
                    "Add output folders whose names encode size (e.g. -30, 30-50, 300-).",
                )
                return
            resolved = self._resolve_output_folder_for_height(target_h)
            if resolved is None:
                messagebox.showwarning(
                    "Auto output",
                    f"No folder in the list matches object height {target_h}px.\n"
                    "Folder basename rules: -N or 0-N (0 ≤ h ≤ N), A-B (inclusive), N- (h ≥ N).",
                )
                return
            out_dir = resolved
            self._select_listbox_index_for_path(out_dir)
        else:
            out_dir = self.out_folder.get().strip()
            if not out_dir:
                messagebox.showwarning("Output", "Please set output folder or enable auto folder by height.")
                return

        if self.bg_work is None:
            messagebox.showwarning("Background", "No background loaded.")
            return
        if not self.obj_paths:
            messagebox.showwarning("Object", "No object PNGs loaded.")
            return

        coords = self.canvas_to_image_coords(event.x, event.y)
        if coords is None:
            self.status.set("Click inside the image area.")
            return

        obj_path = self.obj_paths[self.obj_index % len(self.obj_paths)]
        try:
            obj = Image.open(obj_path)
            obj_r = resize_object_with_height(obj, target_h)
        except OSError as e:
            messagebox.showerror("Error", f"Could not load object:\n{e}")
            return

        rotation_note = ""
        if self.random_rotate_object.get():
            angle_deg = random.uniform(0.0, 360.0)
            obj_r = obj_r.convert("RGBA")
            obj_r = obj_r.rotate(
                angle_deg,
                resample=Image.Resampling.BICUBIC,
                expand=True,
                fillcolor=(0, 0, 0, 0),
            )
            rotation_note = f", rot {angle_deg:.1f}°"

        iw, ih = self.bg_work.size
        ow, oh = obj_r.size
        cx, cy = self.clamp_center(coords[0], coords[1], ow, oh, iw, ih)

        before_state = self.bg_work.copy()
        result = composite_images(self.bg_work.copy(), obj_r, cx, cy)
        os.makedirs(out_dir, exist_ok=True)

        prefix = self.save_prefix.get().strip() or "manual"
        suffix = random.randint(0, 99_999_999)
        base = f"{prefix}-{suffix:08d}"
        fmt = self.save_format.get().lower()
        jpg_q = 95
        if fmt == "png":
            fname = base + ".png"
            fpath = os.path.join(out_dir, fname)
            result.save(fpath, "PNG")
            pil_format = "PNG"
        else:
            fname = base + ".jpg"
            fpath = os.path.join(out_dir, fname)
            result.save(fpath, "JPEG", quality=jpg_q)
            pil_format = "JPEG"

        bbox_left = float(cx - ow // 2)
        bbox_top = float(cy - oh // 2)
        bbox_right = bbox_left + float(ow)
        bbox_bottom = bbox_top + float(oh)
        label = self.labelme_label.get().strip() or "object"
        json_path = os.path.join(out_dir, base + ".json")
        labelme_data = create_labelme_json(
            result,
            fname,
            label,
            bbox_left,
            bbox_top,
            bbox_right,
            bbox_bottom,
            image_format=pil_format,
            jpg_quality=jpg_q,
        )
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(labelme_data, f, indent=2)

        self._undo_stack.append((before_state, fpath, json_path))

        # Show composite as the new working background (stack further placements on top)
        self.bg_work = result
        self.redraw_canvas()
        self._refresh_output_listbox_with_counts()
        self._save_output_folders_state()
        self._focus_canvas_for_shortcuts()

        self.status.set(
            f"Saved: {fpath} + {os.path.basename(json_path)} "
            f"(height {target_h}px, center {cx},{cy}{rotation_note}) — canvas shows result"
        )

    def undo_last_placement(self) -> None:
        """Restore previous canvas state and delete last saved image + labelme JSON."""
        if not self._undo_stack:
            self.status.set("Nothing to undo.")
            return
        before, fpath, jpath = self._undo_stack.pop()
        errors: list[str] = []
        for p in (fpath, jpath):
            try:
                if os.path.isfile(p):
                    os.remove(p)
            except OSError as e:
                errors.append(f"{p}: {e}")
        self.bg_work = before
        self.redraw_canvas()
        if errors:
            messagebox.showwarning(
                "Undo",
                "Canvas restored, but some files could not be deleted:\n" + "\n".join(errors),
            )
            self.status.set("Undone (with file delete warnings).")
        else:
            self.status.set(
                f"Undone — removed {os.path.basename(fpath)} and {os.path.basename(jpath)}"
            )
        self._refresh_output_listbox_with_counts()
        self._focus_canvas_for_shortcuts()

    def run(self) -> None:
        self.mainloop()


def main() -> None:
    app = ManualComposeApp()
    app.run()


if __name__ == "__main__":
    main()
