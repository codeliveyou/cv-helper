#!/usr/bin/env python3
"""
Fix Labelme JSON files so ``imagePath`` matches the actual paired image filename
in the same folder (same stem as the .json file).

Walks recursively under a root directory.

Usage:
  python fix_labelme_imagepath.py --root outputs
  python fix_labelme_imagepath.py --root outputs --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


IMAGE_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".JPG",
    ".JPEG",
    ".PNG",
    ".webp",
    ".WEBP",
)


def find_paired_image(json_path: Path) -> tuple[Path, str] | None:
    """Return (path_to_image, filename_with_ext) or None."""
    stem = json_path.stem
    parent = json_path.parent
    for ext in IMAGE_EXTENSIONS:
        candidate = parent / f"{stem}{ext}"
        if candidate.is_file():
            return candidate, candidate.name
    return None


def normalize_imagepath_value(image_path_field: str) -> str:
    """Compare using basename only (Labelme often stores just filename)."""
    if not image_path_field:
        return ""
    return os.path.basename(image_path_field.replace("\\", "/"))


def fix_json_file(json_path: Path, dry_run: bool) -> bool:
    """
    If imagePath does not match the sibling image filename, update it.
    Returns True if file was modified (or would be in dry-run).
    """
    paired = find_paired_image(json_path)
    if paired is None:
        print(f"  [skip] no paired image for {json_path}")
        return False

    _, correct_name = paired

    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"  [error] cannot read JSON {json_path}: {e}")
        return False

    if not isinstance(data, dict):
        print(f"  [skip] not an object: {json_path}")
        return False

    current = data.get("imagePath")
    if not isinstance(current, str):
        print(f"  [skip] missing or invalid imagePath: {json_path}")
        return False

    if normalize_imagepath_value(current) == correct_name:
        return False

    print(f"  [fix] {json_path.name}")
    print(f"        imagePath: {current!r} -> {correct_name!r}")

    data["imagePath"] = correct_name

    if dry_run:
        return True

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fix Labelme JSON imagePath to match paired image filename (recursive)."
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Root folder to scan recursively",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print changes only, do not write files",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    fixed = 0
    scanned = 0
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if not name.lower().endswith(".json"):
                continue
            json_path = Path(dirpath) / name
            scanned += 1
            if fix_json_file(json_path, args.dry_run):
                fixed += 1

    print(f"Done. Scanned {scanned} JSON file(s), updated {fixed}.")


if __name__ == "__main__":
    main()
