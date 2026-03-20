# cv-helper

Tools to **composite PNG objects onto backgrounds**, export **Labelme** JSON, and fix/rename annotation files. Uses **Python 3.10+**, **Pillow**, and **PyYAML**.

## Install

```bash
cd cv-helper
pip install -r requirements.txt
```

## Project layout (typical)

| Path | Purpose |
|------|---------|
| `config.yaml` | Settings for batch compositing |
| `data/backgrounds/` | Background images (`.jpg` / `.png`) |
| `data/objects/` | Object cutouts (`.png`, often with alpha) |
| `outputs/` | Generated images + JSON (layout depends on script) |
| `.manual_compose_state.json` | GUI: output folder list & options (auto-created) |

---

## 1. Batch compositing — `compose_images.py`

Reads `config.yaml`, places random objects on each background, writes **1280×720** (configurable) **JPG** + Labelme **JSON** (with base64 `imageData`).

```bash
python compose_images.py
```

**Highlights (see `config.yaml`):**

- `background_dir`, `object_dir`, `output_dir`
- Output layout: `outputs/{min_object_height}-{max_object_height}/images/` and `.../json/`
- Filenames: `{output_prefix}-{8-digit random}.jpg` / `.json`
- Placement: `object_x_min` / `object_x_max`, `object_y_min` / `object_y_max`
- `object_label` (e.g. `bird` for Labelme)

---

## 2. Crop object PNGs — `crop_objects.py`

Removes empty transparent margins around objects (alpha bbox). Use **before** or **instead** of relying on full-frame PNGs.

```bash
python crop_objects.py
```

Options are in `config.yaml` under **Object Cropping Settings** (`cropped_object_dir`, `crop_padding`, `crop_overwrite`).

---

## 3. Manual GUI — `manual_compose_app.py`

Interactive compositing: pick folders, object height, click to place, Labelme JSON next to JPG.

```bash
python manual_compose_app.py
```

**Rough workflow**

1. Set **background** / **object** / **output** folders (output can be a list with auto size-buckets).
2. **Object height (px)** — final height after any rotation.
3. **Left-click** image — paste object at click center; saves JPG + JSON.
4. **Right-click** image — undo last save (restore canvas + delete files).
5. **← / →** — previous / next background (not while typing in entries).
6. **↑ / ↓** — previous / next object (object-height spinbox uses arrows for navigation, not value).
7. **Auto folder by object height** — folder **basename** rules: `-30` → 0…30 px, `30-50` → range, `300-` → ≥300 (first matching folder in list wins).

State for output list / auto folder / random rotate is saved in `.manual_compose_state.json`.

---

## 4. Fix `imagePath` in JSON — `fix_labelme_imagepath.py`

Recursively finds `.json` files, pairs them with an image of the **same stem** in the same folder, and sets `imagePath` to that image’s real filename if it was wrong.

```bash
python fix_labelme_imagepath.py --root outputs
python fix_labelme_imagepath.py --root outputs --dry-run
```

---

## 5. Rename JSON + image pairs — `rename_labelme_pairs.py`

Recursively finds pairs `stem.json` + `stem` + image extension. If `stem` **starts with** `--old-prefix`, renames both to `new_prefix + stem[len(old_prefix):]` and updates `imagePath` in the JSON.

```bash
python rename_labelme_pairs.py --root outputs --old-prefix Sec1_Duck --new-prefix Sec2_Cat --dry-run
python rename_labelme_pairs.py --root outputs --old-prefix Sec1_Duck --new-prefix Sec2_Cat
```

Stems that do not start with `--old-prefix` are skipped.

---

## Dependencies

- **Pillow** — images
- **PyYAML** — `config.yaml` for `compose_images.py` / `crop_objects.py`

The manual app uses **tkinter** (usually bundled with Python on Windows).

---

## License

Use and modify as needed for your project.
