#!/usr/bin/env python3
"""
01_select_sample.py - Selects the random sample, downloads the files and writes
the manifest. Run it ONCE per run:

    python scripts/01_select_sample.py --run pilot --n 4 --seed 1
    python scripts/01_select_sample.py --run final

Output in runs/<run>/:
    files/<type>/...     the selected files (not in the repository)
    manifest.csv         one row per selected file: id, type, format, file, source, size, SHA-256
    skipped.csv          every candidate drawn but excluded, with the reason
    text_population.csv  the Gutenberg book ids the text sample was drawn from
    run_info.txt         seed, n, date, kernel commit, catalog SHA-256, population sizes
"""
import argparse
import csv
import hashlib
import io
import random
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import config
from net import polite_get

MANIFEST_FIELDS = ["id", "type", "format", "file", "source", "size_bytes", "sha256"]
SKIPPED_FIELDS = ["type", "source", "reason"]


# --- Helpers -----------------------------------------------------------------

def size_ok(size):
    return config.MIN_BYTES <= size <= config.MAX_BYTES


class Sample:
    """Keeps the selected files, the excluded candidates and facts about the run."""

    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.rows = []
        self.skipped = []
        self.info = {}          # written to run_info.txt at the end

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

def git_output(kdir, *args):
    return subprocess.run(["git", "-C", str(kdir), *args],
                          capture_output=True, text=True).stdout.strip()


def select_code(sample, n, rng):
    print("\n== CODE: Linux kernel ==")
    kdir = config.KERNEL_DIR
    if not (kdir / "Makefile").is_file():
        sys.exit(f"Kernel not found in {kdir}. Clone it first:\n"
                 f"  git clone --depth 1 --branch {config.KERNEL_TAG} "
                 f"https://github.com/torvalds/linux.git {kdir}")
    tags = git_output(kdir, "tag", "--points-at", "HEAD").split()
    if config.KERNEL_TAG not in tags:
        print(f"  WARNING: could not confirm that {kdir} is at tag {config.KERNEL_TAG} "
              f"(tags at HEAD: {tags or 'none'}).")

    # Census: every .c file, sorted so the list is identical on every computer.
    population = sorted(p.relative_to(kdir).as_posix()
                        for p in kdir.rglob("*.c") if p.is_file())
    print(f"  Population: {len(population):,} .c files")
    sample.info["kernel_tag"] = config.KERNEL_TAG
    sample.info["kernel_commit"] = git_output(kdir, "rev-parse", "HEAD") or "unknown"
    sample.info["code_population"] = len(population)
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
    resp = polite_get(config.GUTENBERG_CATALOG_URL)
    resp.raise_for_status()
    catalog = csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig")))

    # Census: catalog entries of type Text whose language is exactly the chosen one.
    population = sorted(int(r["Text#"]) for r in catalog
                        if r["Type"] == "Text"
                        and r["Language"].strip() == config.GUTENBERG_LANGUAGE)
    print(f"  Population: {len(population):,} books "
          f"(Type=Text, Language={config.GUTENBERG_LANGUAGE})")

    # The catalog grows every day, so we keep the exact population we drew from:
    # with this list and the seed, anyone can repeat the draw.
    with open(sample.run_dir / "text_population.csv", "w", newline="") as f:
        f.write("book_id\n" + "".join(f"{b}\n" for b in population))
    sample.info["gutenberg_catalog_sha256"] = hashlib.sha256(resp.content).hexdigest()
    sample.info["text_population"] = f"{len(population)} (list in text_population.csv)"
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
            if r.status_code != 404:
                # Only "404 Not Found" means the file does not exist. Anything else
                # (403, ...) is a problem of ours, not a reason to exclude the book.
                sys.exit(f"Unexpected HTTP {r.status_code} for {base}/{name}. "
                         "Stopping so the book is not excluded by mistake.")
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
    sample.info["image_draw"] = ("Wikimedia Commons API, generator=random (random on the "
                                 "server, not reproducible with the seed)")
    seen = set()
    while sample.count("image") < n:
        r = polite_get(config.COMMONS_API, params=params)
        r.raise_for_status()
        answer = r.json()
        if "error" in answer:
            sys.exit(f"Wikimedia API error: {answer['error']}")
        for page in answer.get("query", {}).get("pages", []):
            if sample.count("image") == n:
                break
            title = page.get("title", "")
            if title in seen:
                continue
            seen.add(title)
            info = (page.get("imageinfo") or [{}])[0]
            mime, size = info.get("mime"), info.get("size")
            # The API adds tracking parameters (?utm_source=...); the file is the same without them.
            url = (info.get("url") or "").split("?")[0]
            source = f"commons:{title}"
            if mime not in config.IMAGE_MIMES:
                sample.skip("image", source, f"not JPG/PNG ({mime})")
                continue
            if size is None or not size_ok(size):
                sample.skip("image", source, f"size out of range ({size} bytes)")
                continue
            img = polite_get(url)
            if img.status_code != 200:
                sample.skip("image", source, f"download failed (HTTP {img.status_code})")
                continue
            if len(img.content) != size:
                sample.skip("image", source, f"downloaded {len(img.content)} bytes, "
                                             f"API says {size}")
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
    elif (run_dir / "files").exists():
        # files/ without manifest = a previous run stopped half-way. Its files are
        # not part of any sample; mixing them with a new run would be confusing.
        sys.exit(f"{run_dir}/files exists but there is no manifest: a previous run did "
                 "not finish. Delete that files/ folder and run the script again.")
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"Run '{args.run}': n={args.n} per type, seed={args.seed}")
    sample = Sample(run_dir)
    sample.info.update({
        "run": args.run,
        "date": datetime.now().isoformat(timespec="seconds"),
        "seed": args.seed,
        "n_per_type": args.n,
        "size_range_bytes": f"{config.MIN_BYTES}-{config.MAX_BYTES}",
    })
    # One independent random generator per type: redoing one type never changes another.
    select_code(sample, args.n, random.Random(f"{args.seed}-code"))
    select_text(sample, args.n, random.Random(f"{args.seed}-text"))
    select_images(sample, args.n)

    write_csv(run_dir / "manifest.csv", MANIFEST_FIELDS, sample.rows)
    write_csv(run_dir / "skipped.csv", SKIPPED_FIELDS, sample.skipped)
    sample.info["selected"] = len(sample.rows)
    sample.info["excluded"] = len(sample.skipped)
    (run_dir / "run_info.txt").write_text(
        "".join(f"{k}: {v}\n" for k, v in sample.info.items()), encoding="utf-8")
    print(f"\nDone. {len(sample.rows)} files selected, {len(sample.skipped)} candidates "
          f"excluded.\nManifest: {run_dir / 'manifest.csv'}")


if __name__ == "__main__":
    main()
