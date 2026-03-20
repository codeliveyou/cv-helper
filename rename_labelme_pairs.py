#!/usr/bin/env python3
"""
Rename Labelme pairs (.json + .jpg/.jpeg/.png with same stem) under a root folder,
replacing the leading prefix in the stem. Updates ``imagePath`` inside the JSON
after rename.

Walks recursively. Only processes folders where BOTH the JSON and image exist.

Usage:
  python rename_labelme_pairs.py --root outputs --old-prefix abc --new-prefix xyz
  python rename_labelme_pairs.py --root outputs --old-prefix Sec1_Duck --new-prefix Sec2_Cat --dry-run

Stem must start with --old-prefix; new stem is --new-prefix + stem[len(old-prefix):].
Example: old Sec1_Duck-123 + new XYZ -> XYZ-123 (if old-prefix is Sec1_Duck).
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
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


def find_image_path(parent: Path, stem: str) -> Path | None:
    for ext in IMAGE_EXTENSIONS:
        p = parent / f"{stem}{ext}"
        if p.is_file():
            return p
    return None


def image_filename_for_stem(parent: Path, stem: str) -> str | None:
    p = find_image_path(parent, stem)
    return p.name if p else None


def rename_pair_via_temp(
    json_path: Path,
    image_path: Path,
    new_stem: str,
    dry_run: bool,
) -> None:
    """Rename json + image to new_stem, using temp files to avoid name collisions."""
    parent = json_path.parent
    new_json = parent / f"{new_stem}.json"
    new_image_name = f"{new_stem}{image_path.suffix}"

    if new_json.exists() or (parent / new_image_name).exists():
        raise FileExistsError(
            f"target exists: {new_json.name} or {new_image_name} in {parent}"
        )

    if dry_run:
        print(
            f"  [dry-run] {json_path.name} + {image_path.name} -> "
            f"{new_stem}.json + {new_image_name}"
        )
        return

    fd, tmp_json = tempfile.mkstemp(suffix=".json", dir=str(parent))
    os.close(fd)
    fd, tmp_img = tempfile.mkstemp(suffix=image_path.suffix, dir=str(parent))
    os.close(fd)
    tmp_json_path = Path(tmp_json)
    tmp_img_path = Path(tmp_img)

    json_path.rename(tmp_json_path)
    image_path.rename(tmp_img_path)
    tmp_json_path.rename(new_json)
    tmp_img_path.rename(parent / new_image_name)

    with open(new_json, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data["imagePath"] = new_image_name
        with open(new_json, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def collect_stems_with_pairs(root: Path) -> dict[Path, set[str]]:
    """dir_path -> set of stems that have both .json and an image."""
    json_by_dir: dict[Path, set[str]] = {}
    image_stems_by_dir: dict[Path, set[str]] = {}

    for dirpath, _names, filenames in os.walk(root):
        pdir = Path(dirpath)
        for name in filenames:
            path = pdir / name
            lower = name.lower()
            if lower.endswith(".json"):
                json_by_dir.setdefault(pdir, set()).add(path.stem)
            else:
                for ext in IMAGE_EXTENSIONS:
                    if lower.endswith(ext.lower()):
                        image_stems_by_dir.setdefault(pdir, set()).add(Path(name).stem)
                        break

    pairs: dict[Path, set[str]] = {}
    for pdir, jstems in json_by_dir.items():
        imgs = image_stems_by_dir.get(pdir, set())
        both = jstems & imgs
        if both:
            pairs[pdir] = both
    return pairs


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rename Labelme JSON+image pairs by replacing stem prefix (recursive)."
    )
    parser.add_argument("--root", type=Path, required=True, help="Root folder to scan")
    parser.add_argument(
        "--old-prefix",
        required=True,
        help="Stem must start with this (e.g. Sec1_Duck)",
    )
    parser.add_argument(
        "--new-prefix",
        required=True,
        help="Replacement for old-prefix at start of stem (e.g. Sec2_Cat)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned renames only",
    )
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    old_p = args.old_prefix
    new_p = args.new_prefix

    pairs_by_dir = collect_stems_with_pairs(root)
    renamed = 0
    skipped = 0

    # Deterministic order
    for pdir in sorted(pairs_by_dir.keys(), key=str):
        for stem in sorted(pairs_by_dir[pdir]):
            if not stem.startswith(old_p):
                skipped += 1
                continue
            new_stem = new_p + stem[len(old_p) :]
            if new_stem == stem:
                skipped += 1
                continue

            json_path = pdir / f"{stem}.json"
            img_path = find_image_path(pdir, stem)
            if img_path is None or not json_path.is_file():
                continue

            try:
                rename_pair_via_temp(json_path, img_path, new_stem, args.dry_run)
            except FileExistsError as e:
                print(f"  [skip] {e}")
                skipped += 1
                continue
            except OSError as e:
                print(f"  [error] {json_path}: {e}")
                skipped += 1
                continue

            print(f"  [ok] {pdir / stem}* -> {new_stem}.*")
            renamed += 1

    print(f"Done. Renamed {renamed} pair(s), skipped {skipped} stem(s) (no prefix match or error).")


if __name__ == "__main__":
    main()
