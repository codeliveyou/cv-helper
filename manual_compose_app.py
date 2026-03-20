"""
Manual image compositing GUI: pick background/object folders, navigate with arrows,
click to place object and save to output folder.
"""

from __future__ import annotations

import json
import os
import random
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


class ManualComposeApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Manual compose — background + object")
        self.minsize(900, 700)

        self.bg_folder = tk.StringVar()
        self.obj_folder = tk.StringVar()
        self.out_folder = tk.StringVar()
        self.min_height = tk.IntVar(value=50)
        self.max_height = tk.IntVar(value=200)
        self.output_w = tk.IntVar(value=1280)
        self.output_h = tk.IntVar(value=720)
        self.save_prefix = tk.StringVar(value="manual")
        self.save_format = tk.StringVar(value="jpg")  # jpg or png
        self.random_obj_on_next_bg = tk.BooleanVar(value=False)
        self.labelme_label = tk.StringVar(value="bird")

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

        self._build_ui()
        self.bind("<Right>", lambda e: self.next_background())
        self.bind("<Down>", lambda e: self.next_object())
        self.bind("<Left>", lambda e: self.undo_last_placement())
        self.bind("<Shift-Left>", lambda e: self.prev_background())
        self.bind("<Up>", lambda e: self.prev_object())

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
        ttk.Button(row2, text="Output folder…", command=self.pick_out_folder).pack(
            side=tk.LEFT, **pad
        )
        ttk.Entry(row2, textvariable=self.out_folder, width=50).pack(
            side=tk.LEFT, fill=tk.X, expand=True, **pad
        )

        # Row: height + output size
        row3 = ttk.Frame(frm)
        row3.pack(fill=tk.X, **pad)
        ttk.Label(row3, text="Object height min:").pack(side=tk.LEFT, **pad)
        ttk.Spinbox(row3, from_=1, to=2000, textvariable=self.min_height, width=8).pack(
            side=tk.LEFT, **pad
        )
        ttk.Label(row3, text="max:").pack(side=tk.LEFT)
        ttk.Spinbox(row3, from_=1, to=2000, textvariable=self.max_height, width=8).pack(
            side=tk.LEFT, **pad
        )
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
        ttk.Button(row5, text="← Undo last", command=self.undo_last_placement).pack(
            side=tk.LEFT, **pad
        )
        ttk.Checkbutton(
            row5,
            text="Pick random object when moving to next background",
            variable=self.random_obj_on_next_bg,
        ).pack(side=tk.LEFT, padx=(16, 0))

        self.status = tk.StringVar(value="Load folders, then click on the image to place object.")
        ttk.Label(frm, textvariable=self.status, wraplength=880).pack(fill=tk.X, **pad)

        # Main area: canvas + object preview
        main_row = ttk.Frame(frm)
        main_row.pack(fill=tk.BOTH, expand=True, **pad)
        main_row.columnconfigure(0, weight=1)
        main_row.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(main_row, bg="#222", highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 8))
        self.canvas.bind("<Button-1>", self.on_canvas_click)
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
            text="Shortcuts: Right = next background · Down = next object · Left = undo last save · "
            "Shift+Left = previous background · Up = previous object",
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

    def pick_out_folder(self) -> None:
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.out_folder.set(d)

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

    def prev_background(self) -> None:
        if not self.bg_paths:
            return
        self.bg_index = (self.bg_index - 1) % len(self.bg_paths)
        self.load_current_background()

    def next_object(self) -> None:
        if not self.obj_paths:
            messagebox.showinfo("Info", "No objects loaded.")
            return
        self.obj_index = (self.obj_index + 1) % len(self.obj_paths)
        self.set_status()
        self.update_object_preview()

    def prev_object(self) -> None:
        if not self.obj_paths:
            return
        self.obj_index = (self.obj_index - 1) % len(self.obj_paths)
        self.set_status()
        self.update_object_preview()

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

    def on_canvas_click(self, event: tk.Event) -> None:
        out_dir = self.out_folder.get().strip()
        if not out_dir:
            messagebox.showwarning("Output", "Please set output folder.")
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

        min_h = int(self.min_height.get())
        max_h = int(self.max_height.get())
        if min_h > max_h:
            min_h, max_h = max_h, min_h
        target_h = random.randint(min_h, max_h)

        obj_path = self.obj_paths[self.obj_index % len(self.obj_paths)]
        try:
            obj = Image.open(obj_path)
            obj_r = resize_object_with_height(obj, target_h)
        except OSError as e:
            messagebox.showerror("Error", f"Could not load object:\n{e}")
            return

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

        self.status.set(
            f"Saved: {fpath} + {os.path.basename(json_path)} "
            f"(height {target_h}px, center {cx},{cy}) — canvas shows result"
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

    def run(self) -> None:
        self.mainloop()


def main() -> None:
    app = ManualComposeApp()
    app.run()


if __name__ == "__main__":
    main()
