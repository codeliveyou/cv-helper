#!/usr/bin/env python3
"""
Replace a class label with another in Labelme-style JSON files (``shapes[].label``).

Walks ``--input`` recursively for ``*.json``. Optionally records each run in a
**resume** report file (append-only history) under the input folder.

Usage:
  python replace_labelme_labels.py --input ./outputs --old-label bird --new-label duck
  python replace_labelme_labels.py -i ./data --old bird --new duck --dry-run
  python replace_labelme_labels.py -i ./outputs --old bird --new duck --resume ./outputs/label_resume.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_RESUME_NAME = "label_replace_resume.json"


def replace_labels_in_obj(
    data: object,
    old_label: str,
    new_label: str,
) -> int:
    """
    Walk Labelme-like structure: top-level ``shapes`` list with ``label`` keys.
    Returns number of replacements.
    """
    if not isinstance(data, dict):
        return 0
    shapes = data.get("shapes")
    if not isinstance(shapes, list):
        return 0
    n = 0
    for shape in shapes:
        if not isinstance(shape, dict):
            continue
        if shape.get("label") == old_label:
            shape["label"] = new_label
            n += 1
    return n


def process_json_file(
    path: Path,
    old_label: str,
    new_label: str,
    dry_run: bool,
) -> int:
    """Returns number of label replacements in this file (0 if unchanged / skip)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return -1  # signal error

    n = replace_labels_in_obj(data, old_label, new_label)
    if n <= 0:
        return 0

    if dry_run:
        return n

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return n


def load_resume(path: Path) -> dict:
    if not path.is_file():
        return {"runs": []}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return {"runs": []}
        if "runs" not in d or not isinstance(d["runs"], list):
            d = {"runs": []}
        return d
    except (OSError, json.JSONDecodeError):
        return {"runs": []}


def append_resume(
    resume_path: Path,
    old_label: str,
    new_label: str,
    files_modified: list[str],
    total_replacements: int,
    errors: int,
    dry_run: bool,
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "old_label": old_label,
        "new_label": new_label,
        "dry_run": dry_run,
        "files_modified_count": len(files_modified),
        "shapes_relabeled": total_replacements,
        "json_errors": errors,
        "files_modified": files_modified,
    }
    data = load_resume(resume_path)
    data["runs"].append(entry)
    data["last_run"] = entry
    resume_path.parent.mkdir(parents=True, exist_ok=True)
    with open(resume_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def collect_json_files(root: Path) -> list[Path]:
    out: list[Path] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".json"):
                out.append(Path(dirpath) / name)
    return sorted(out)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Replace Labelme shape labels in JSON files (recursive) and update resume log."
    )
    p.add_argument(
        "-i",
        "--input",
        type=Path,
        required=True,
        help="Root folder to scan for .json files",
    )
    p.add_argument(
        "--old-label",
        "--old",
        dest="old_label",
        required=True,
        help="Label text to replace (exact match)",
    )
    p.add_argument(
        "--new-label",
        "--new",
        dest="new_label",
        required=True,
        help="New label text",
    )
    p.add_argument(
        "--resume",
        type=Path,
        default=None,
        help=f"Resume/report JSON path (default: INPUT/{DEFAULT_RESUME_NAME})",
    )
    p.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not write or update the resume file",
    )
    p.add_argument("--dry-run", action="store_true", help="Print only, do not write JSON files")
    args = p.parse_args()

    root = args.input.resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    resume_path = None
    if not args.no_resume:
        resume_path = (args.resume or (root / DEFAULT_RESUME_NAME)).resolve()

    files = collect_json_files(root)
    modified: list[str] = []
    total_shapes = 0
    errors = 0

    for jpath in files:
        # Skip the resume file itself if it lives under root
        if resume_path and jpath.resolve() == resume_path:
            continue

        n = process_json_file(jpath, args.old_label, args.new_label, args.dry_run)
        if n < 0:
            errors += 1
            print(f"[error] {jpath}")
            continue
        if n == 0:
            continue

        total_shapes += n
        rel = str(jpath.relative_to(root)) if jpath.is_relative_to(root) else str(jpath)
        modified.append(rel)
        print(f"[{'dry-run' if args.dry_run else 'ok'}] {rel}  (+{n} shape(s))")

    print(
        f"\nDone. Files with replacements: {len(modified)}, "
        f"total shapes relabeled: {total_shapes}, json read errors: {errors}."
    )

    if resume_path and not args.no_resume:
        append_resume(
            resume_path,
            args.old_label,
            args.new_label,
            modified,
            total_shapes,
            errors,
            args.dry_run,
        )
        print(f"Resume updated: {resume_path}")


if __name__ == "__main__":
    main()
