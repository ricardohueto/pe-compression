#!/usr/bin/env python3
"""
01_select_sample.py - Selects the random sample, downloads the files and writes
the manifest. Run it ONCE per run:

    python scripts/01_select_sample.py --run pilot --n 4 --seed 1
    python scripts/01_select_sample.py --run final

Output in runs/<run>/:
    files/<type>/...   the selected files
    manifest.csv       one row per selected file: id, type, format, file, source, size, SHA-256
    skipped.csv        every candidate drawn but excluded, with the reason
"""
import argparse
import csv
import hashlib
import io
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

import config

SESSION = requests.Session()
SESSION.headers["User-Agent"] = config.USER_AGENT

MANIFEST_FIELDS = ["id", "type", "format", "file", "source", "size_bytes", "sha256"]
SKIPPED_FIELDS = ["type", "source", "reason"]


# --- Helpers -----------------------------------------------------------------

def polite_get(url, **kwargs):
    """GET with a pause before every request, so we never overload a server."""
    time.sleep(config.REQUEST_DELAY_S)
    return SESSION.get(url, timeout=120, **kwargs)


def size_ok(size):
    return config.MIN_BYTES <= size <= config.MAX_BYTES


class Sample:
    """Keeps the selected files and the excluded candidates."""

    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.rows = []
        self.skipped = []

    def count(self, ftype):
        return sum(1 for r in self.rows if r["type"] == ftype)

    def add(self, ftype, fmt, source, content, filename):
        n = self.count(ftype) + 1
        rel = Path("files") / ftype / filename
        dest = self.run_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        self.rows.append({
            "id": f"{ftype}_{n:03d}",
            "type": ftype,
            "format": fmt,
            "file": rel.as_posix(),
            "source": source,
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        })
        print(f"  [{ftype} {n:3d}] {source} ({len(content):,} bytes)")

    def skip(self, ftype, source, reason):
        self.skipped.append({"type": ftype, "source": source, "reason": reason})
        print(f"  [{ftype} skip] {source}: {reason}")


# --- Code: Linux kernel ----------------------------------------------------------

def select_code(sample, n, rng):
    print("\n== CODE: Linux kernel ==")
    kdir = config.KERNEL_DIR
    if not (kdir / "Makefile").is_file():
        sys.exit(f"Kernel not found in {kdir}. Clone it first:\n"
                 f"  git clone --depth 1 --branch {config.KERNEL_TAG} "
                 f"https://github.com/torvalds/linux.git {kdir}")
    tags = subprocess.run(["git", "-C", str(kdir), "tag", "--points-at", "HEAD"],
                          capture_output=True, text=True).stdout.split()
    if config.KERNEL_TAG not in tags:
        print(f"  WARNING: could not confirm that {kdir} is at tag {config.KERNEL_TAG} "
              f"(tags at HEAD: {tags or 'none'}).")

    # Census: every .c file, sorted so the list is identical on every computer.
    population = sorted(p.relative_to(kdir).as_posix()
                        for p in kdir.rglob("*.c") if p.is_file())
    print(f"  Population: {len(population):,} .c files")
    rng.shuffle(population)

    for rel in population:
        if sample.count("code") == n:
            break
        content = (kdir / rel).read_bytes()
        source = f"linux/{config.KERNEL_TAG}/{rel}"
        if not size_ok(len(content)):
            sample.skip("code", source, f"size out of range ({len(content)} bytes)")
            continue
        sample.add("code", "c", source, content, rel.replace("/", "__"))

    if sample.count("code") < n:
        sys.exit("Not enough code files in the population.")


# --- Text: Project Gutenberg -----------------------------------------------------

def gutenberg_dir(book_id):
    """Mirror folder of a book: 84 -> '8/84', 12714 -> '1/2/7/1/12714', 7 -> '0/7'."""
    s = str(book_id)
    prefix = "0" if len(s) == 1 else "/".join(s[:-1])
    return f"{prefix}/{s}"


def select_text(sample, n, rng):
    print("\n== TEXT: Project Gutenberg ==")
    resp = SESSION.get(config.GUTENBERG_CATALOG_URL, timeout=300)
    resp.raise_for_status()
    catalog = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))

    # Census: catalog entries of type Text whose language is exactly the chosen one.
    population = sorted(int(r["Text#"]) for r in catalog
                        if r["Type"] == "Text"
                        and r["Language"].strip() == config.GUTENBERG_LANGUAGE)
    print(f"  Population: {len(population):,} books "
          f"(Type=Text, Language={config.GUTENBERG_LANGUAGE})")
    rng.shuffle(population)

    for book_id in population:
        if sample.count("text") == n:
            break
        source = f"gutenberg:{book_id}"
        base = f"{config.GUTENBERG_MIRROR}/{gutenberg_dir(book_id)}"
        content, url = None, None
        for name in (f"{book_id}-0.txt", f"{book_id}.txt", f"{book_id}-8.txt"):
            r = polite_get(f"{base}/{name}")
            if r.status_code == 200:
                content, url = r.content, f"{base}/{name}"
                break
        if content is None:
            sample.skip("text", source, "no plain-text file on the mirror")
            continue
        if not size_ok(len(content)):
            sample.skip("text", source, f"size out of range ({len(content)} bytes)")
            continue
        sample.add("text", "txt", url, content, f"{book_id}.txt")

    if sample.count("text") < n:
        sys.exit("Not enough books in the population.")


# --- Images: Wikimedia Commons ---------------------------------------------------

def select_images(sample, n):
    print("\n== IMAGE: Wikimedia Commons ==")
    params = {
        "action": "query", "format": "json", "formatversion": 2,
        "generator": "random", "grnnamespace": 6, "grnlimit": 10,   # 6 = File namespace
        "prop": "imageinfo", "iiprop": "url|size|mime",
    }
    seen = set()
    while sample.count("image") < n:
        r = polite_get(config.COMMONS_API, params=params)
        r.raise_for_status()
        for page in r.json().get("query", {}).get("pages", []):
            if sample.count("image") == n:
                break
            title = page.get("title", "")
            if title in seen:
                continue
            seen.add(title)
            info = (page.get("imageinfo") or [{}])[0]
            mime, size, url = info.get("mime"), info.get("size"), info.get("url")
            source = f"commons:{title}"
            if mime not in config.IMAGE_MIMES:
                sample.skip("image", source, f"not JPG/PNG ({mime})")
                continue
            if size is None or not size_ok(size):
                sample.skip("image", source, f"size out of range ({size} bytes)")
                continue
            img = polite_get(url)
            if img.status_code != 200 or len(img.content) != size:
                sample.skip("image", source, f"download failed (HTTP {img.status_code})")
                continue
            fmt = config.IMAGE_MIMES[mime]
            sample.add("image", fmt, url, img.content, f"{sample.count('image') + 1:03d}.{fmt}")


# --- Main ------------------------------------------------------------------------

def write_csv(path, fields, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="Select and download the random sample.")
    ap.add_argument("--run", required=True, help="run name, e.g. pilot or final")
    ap.add_argument("--n", type=int, default=config.N_PER_TYPE, help="files per type")
    ap.add_argument("--seed", type=int, default=config.SEED, help="random seed")
    ap.add_argument("--force", action="store_true", help="overwrite an existing run")
    args = ap.parse_args()

    if "YOUR_EMAIL" in config.USER_AGENT:
        sys.exit("Edit USER_AGENT in scripts/config.py and put your e-mail "
                 "(Wikimedia requires a contact address).")

    run_dir = config.RUNS_DIR / args.run
    if (run_dir / "manifest.csv").exists():
        if not args.force:
            sys.exit(f"{run_dir}/manifest.csv already exists. The sample is selected only "
                     "once; use --force only if you really want to redo it.")
        shutil.rmtree(run_dir / "files", ignore_errors=True)
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Run '{args.run}': n={args.n} per type, seed={args.seed}")
    sample = Sample(run_dir)
    # One independent random generator per type: redoing one type never changes another.
    select_code(sample, args.n, random.Random(f"{args.seed}-code"))
    select_text(sample, args.n, random.Random(f"{args.seed}-text"))
    select_images(sample, args.n)

    write_csv(run_dir / "manifest.csv", MANIFEST_FIELDS, sample.rows)
    write_csv(run_dir / "skipped.csv", SKIPPED_FIELDS, sample.skipped)
    print(f"\nDone. {len(sample.rows)} files selected, {len(sample.skipped)} candidates "
          f"excluded.\nManifest: {run_dir / 'manifest.csv'}")


if __name__ == "__main__":
    main()
