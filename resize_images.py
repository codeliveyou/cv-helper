#!/usr/bin/env python3
"""
Resize all images in a folder to a target resolution.

- **Fit (crop + resize)**: preserve aspect ratio, center-crop then scale to exact WxH
  (same logic as ``compose_images.crop_and_resize_to_target``).
- **Stretch**: scale to WxH without preserving aspect ratio.

Supports a GUI (default) or command-line mode.

GUI:
  python resize_images.py

CLI:
  python resize_images.py -i ./photos -W 1280 -H 720
  python resize_images.py -i ./photos -W 1280 -H 720 -o ./out --recursive
  python resize_images.py -i ./photos -W 800 -H 600 --stretch
"""

from __future__ import annotations

import argparse
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image

from compose_images import crop_and_resize_to_target

IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".webp",
    ".tif",
    ".tiff",
)
_IMAGE_EXT_SET = {e.lower() for e in IMAGE_EXTENSIONS}


def _is_image_path(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in _IMAGE_EXT_SET


def collect_image_files(root: Path, recursive: bool) -> list[Path]:
    files: list[Path] = []
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                path = Path(dirpath) / name
                if _is_image_path(path):
                    files.append(path)
    else:
        if not root.is_dir():
            return []
        for name in os.listdir(root):
            p = root / name
            if _is_image_path(p):
                files.append(p)
    return sorted(files)


def resize_one(
    src: Path,
    dst: Path,
    width: int,
    height: int,
    stretch: bool,
    jpeg_quality: int,
) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    if im.mode in ("P", "PA"):
        im = im.convert("RGBA")

    if stretch:
        out = im.resize((width, height), Image.Resampling.LANCZOS)
    else:
        work = im
        if work.mode == "RGBA":
            rgb = Image.new("RGB", work.size, (255, 255, 255))
            rgb.paste(work, mask=work.split()[3])
            work = rgb
        elif work.mode != "RGB":
            work = work.convert("RGB")
        out = crop_and_resize_to_target(work, width, height)

    ext = dst.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        if out.mode == "RGBA":
            bg = Image.new("RGB", out.size, (255, 255, 255))
            bg.paste(out, mask=out.split()[3])
            out = bg
        elif out.mode != "RGB":
            out = out.convert("RGB")
        out.save(dst, "JPEG", quality=jpeg_quality)
    else:
        out.save(dst)


def run_batch(
    input_dir: Path,
    output_dir: Path,
    width: int,
    height: int,
    *,
    recursive: bool,
    stretch: bool,
    jpeg_quality: int,
) -> tuple[int, int]:
    """Returns (ok_count, error_count)."""
    files = collect_image_files(input_dir, recursive)
    ok, err = 0, 0
    input_dir = input_dir.resolve()

    for src in files:
        try:
            rel = src.relative_to(input_dir)
        except ValueError:
            rel = src.name
        dst = output_dir / rel
        dst = dst.with_suffix(src.suffix.lower())
        try:
            resize_one(src, dst, width, height, stretch, jpeg_quality)
            ok += 1
        except OSError as e:
            print(f"[error] {src}: {e}", file=sys.stderr)
            err += 1
    return ok, err


def cli_main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Resize images in a folder to target resolution.")
    p.add_argument("-i", "--input", type=Path, required=True, help="Input folder")
    p.add_argument("-o", "--output", type=Path, default=None, help="Output folder (default: input/resized_WxH)")
    p.add_argument("-W", "--width", type=int, required=True)
    p.add_argument("-H", "--height", type=int, required=True)
    p.add_argument("--recursive", "-r", action="store_true", help="Include subfolders")
    p.add_argument("--stretch", action="store_true", help="Stretch to WxH (ignore aspect ratio)")
    p.add_argument("--jpeg-quality", type=int, default=95, metavar="Q")
    args = p.parse_args(argv)

    inp = args.input.resolve()
    if not inp.is_dir():
        raise SystemExit(f"Not a directory: {inp}")

    out = args.output
    if out is None:
        out = inp / f"resized_{args.width}x{args.height}"
    else:
        out = out.resolve()

    ok, err = run_batch(
        inp,
        out,
        args.width,
        args.height,
        recursive=args.recursive,
        stretch=args.stretch,
        jpeg_quality=args.jpeg_quality,
    )
    print(f"Done. Resized {ok} file(s), {err} error(s). Output: {out}")


class ResizeImagesApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Resize images")
        self.minsize(520, 380)

        self.input_dir = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.width = tk.IntVar(value=1280)
        self.height = tk.IntVar(value=720)
        self.recursive = tk.BooleanVar(value=False)
        self.stretch = tk.BooleanVar(value=False)
        self.jpeg_quality = tk.IntVar(value=95)
        self.use_custom_output = tk.BooleanVar(value=False)

        pad = {"padx": 8, "pady": 6}
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        row0 = ttk.Frame(frm)
        row0.pack(fill=tk.X, **pad)
        ttk.Button(row0, text="Select input folder…", command=self.pick_input).pack(side=tk.LEFT)
        ttk.Entry(row0, textvariable=self.input_dir, width=55).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

        row1 = ttk.Frame(frm)
        row1.pack(fill=tk.X, **pad)
        ttk.Checkbutton(row1, text="Use custom output folder", variable=self.use_custom_output).pack(
            side=tk.LEFT
        )
        ttk.Button(row1, text="Browse…", command=self.pick_output).pack(side=tk.LEFT, padx=(12, 0))

        row1b = ttk.Frame(frm)
        row1b.pack(fill=tk.X, **pad)
        ttk.Entry(row1b, textvariable=self.output_dir, width=60).pack(fill=tk.X, expand=True)

        row2 = ttk.Frame(frm)
        row2.pack(fill=tk.X, **pad)
        ttk.Label(row2, text="Width:").pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=1, to=16384, textvariable=self.width, width=8).pack(side=tk.LEFT, padx=(4, 16))
        ttk.Label(row2, text="Height:").pack(side=tk.LEFT)
        ttk.Spinbox(row2, from_=1, to=16384, textvariable=self.height, width=8).pack(side=tk.LEFT, padx=4)

        row3 = ttk.Frame(frm)
        row3.pack(fill=tk.X, **pad)
        ttk.Checkbutton(row3, text="Include subfolders (recursive)", variable=self.recursive).pack(side=tk.LEFT)
        ttk.Checkbutton(row3, text="Stretch to exact size (ignore aspect ratio)", variable=self.stretch).pack(
            side=tk.LEFT, padx=(16, 0)
        )

        row4 = ttk.Frame(frm)
        row4.pack(fill=tk.X, **pad)
        ttk.Label(row4, text="JPEG quality (1–100):").pack(side=tk.LEFT)
        ttk.Spinbox(row4, from_=1, to=100, textvariable=self.jpeg_quality, width=6).pack(side=tk.LEFT, padx=4)

        ttk.Button(frm, text="Resize images", command=self.on_run).pack(pady=12)

        ttk.Label(frm, text="Fit mode: center-crop then resize to exact resolution (like video frame).").pack(
            anchor=tk.W
        )

        self.log = tk.Text(frm, height=10, wrap=tk.WORD, state=tk.DISABLED)
        self.log.pack(fill=tk.BOTH, expand=True, pady=8)

    def pick_input(self) -> None:
        d = filedialog.askdirectory(title="Select folder with images")
        if d:
            self.input_dir.set(d)

    def pick_output(self) -> None:
        d = filedialog.askdirectory(title="Select output folder")
        if d:
            self.output_dir.set(d)
            self.use_custom_output.set(True)

    def _log(self, msg: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def on_run(self) -> None:
        inp = self.input_dir.get().strip()
        if not inp or not os.path.isdir(inp):
            messagebox.showwarning("Input", "Select a valid input folder.")
            return
        inp_p = Path(inp).resolve()
        w, h = int(self.width.get()), int(self.height.get())
        if w < 1 or h < 1:
            messagebox.showwarning("Size", "Width and height must be positive.")
            return

        if self.use_custom_output.get():
            out_s = self.output_dir.get().strip()
            if not out_s:
                messagebox.showwarning("Output", "Set an output folder or disable custom output.")
                return
            out_p = Path(out_s).resolve()
        else:
            out_p = inp_p / f"resized_{w}x{h}"

        self.log.configure(state=tk.NORMAL)
        self.log.delete("1.0", tk.END)
        self.log.configure(state=tk.DISABLED)
        self._log(f"Input: {inp_p}")
        self._log(f"Output: {out_p}")
        self._log(f"Size: {w}x{h}, stretch={self.stretch.get()}, recursive={self.recursive.get()}")
        self.update_idletasks()

        try:
            ok, err = run_batch(
                inp_p,
                out_p,
                w,
                h,
                recursive=self.recursive.get(),
                stretch=self.stretch.get(),
                jpeg_quality=int(self.jpeg_quality.get()),
            )
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._log(f"Failed: {e}")
            return

        self._log(f"Finished: {ok} ok, {err} errors.")
        messagebox.showinfo("Done", f"Resized {ok} image(s).\nOutput:\n{out_p}")


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        ResizeImagesApp().mainloop()
        return
    if argv[0] in ("-h", "--help"):
        cli_main(["--help"])
        return
    if "-i" in argv or "--input" in argv:
        cli_main(argv)
        return
    print(
        "Unknown arguments. Use: python resize_images.py -i FOLDER -W WIDTH -H HEIGHT\n"
        "Or run with no arguments to open the GUI.",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
