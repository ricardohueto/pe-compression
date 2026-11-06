#!/usr/bin/env python3
"""
00_fetch_from_manifest.py - Gets again the files of an existing run, from the
sources written in its manifest, and verifies each one with its SHA-256.

The sample files are not stored in the repository. Use this script to repeat
the measurements on exactly the same sample, without selecting a new one:

    python scripts/00_fetch_from_manifest.py --run pilot
    python scripts/02_measure.py --run pilot --force
    python scripts/03_check.py --run pilot --n 4

Code files are copied from the local kernel clone (external/linux); text and
images are downloaded from the URL in the "source" column. Files that are
already present and correct are not downloaded again.
"""
import argparse
import csv
import hashlib
import sys

import config
from net import polite_get

KERNEL_PREFIX = f"linux/{config.KERNEL_TAG}/"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def fetch(source):
    """Returns the bytes of one source (kernel path or URL), or None if not available."""
    if source.startswith(KERNEL_PREFIX):
        path = config.KERNEL_DIR / source[len(KERNEL_PREFIX):]
        return path.read_bytes() if path.is_file() else None
    r = polite_get(source)
    return r.content if r.status_code == 200 else None


def main():
    ap = argparse.ArgumentParser(description="Download the files of a run from its manifest.")
    ap.add_argument("--run", required=True, help="run name, e.g. pilot or final")
    args = ap.parse_args()

    run_dir = config.RUNS_DIR / args.run
    manifest_path = run_dir / "manifest.csv"
    if not manifest_path.exists():
        sys.exit(f"{manifest_path} not found.")
    with open(manifest_path, newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    if (any(r["source"].startswith(KERNEL_PREFIX) for r in manifest)
            and not (config.KERNEL_DIR / "Makefile").is_file()):
        sys.exit(f"Kernel not found in {config.KERNEL_DIR}. Clone it first:\n"
                 f"  git clone --depth 1 --branch {config.KERNEL_TAG} "
                 f"https://github.com/torvalds/linux.git {config.KERNEL_DIR}")

    problems = 0
    for i, row in enumerate(manifest, 1):
        dest = run_dir / row["file"]
        # Safety: a manifest must only write inside its own run folder.
        if not dest.resolve().is_relative_to(run_dir.resolve()):
            sys.exit(f"ERROR: {row['id']} has an invalid path: {row['file']}")
        label = f"[{i:3d}/{len(manifest)}] {row['id']}"

        if dest.is_file() and sha256(dest.read_bytes()) == row["sha256"]:
            print(f"{label}: already present")
            continue
        content = fetch(row["source"])
        if content is None:
            print(f"{label}: ERROR, not available at {row['source']}")
            problems += 1
        elif sha256(content) != row["sha256"]:
            print(f"{label}: ERROR, the file at the source has changed (SHA-256 mismatch)")
            problems += 1
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
            print(f"{label}: fetched and verified")

    if problems:
        sys.exit(f"\n{problems} file(s) could not be recovered. The rest are verified.")
    print(f"\nAll {len(manifest)} files present and verified with SHA-256.")


if __name__ == "__main__":
    main()
