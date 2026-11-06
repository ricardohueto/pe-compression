#!/usr/bin/env python3
"""
02_measure.py - Compresses every file of the manifest with gzip and zstd and
writes the data file. It can be rerun as many times as needed.

    python scripts/02_measure.py --run final

Output in runs/<run>/:
    results.csv        one row per file (the data for R)
    environment.txt    software and hardware used (copy it to the protocol/report)
"""
import argparse
import csv
import gzip
import hashlib
import platform
import random
import sys
import time
import zlib
from datetime import datetime
from pathlib import Path

import zstandard

import config

RESULT_FIELDS = ["id", "type", "format", "size_bytes",
                 "size_gzip", "size_zstd", "ratio_gzip", "ratio_zstd",
                 "time_gzip", "time_zstd", "first_algo"]

ZSTD_COMPRESSOR = zstandard.ZstdCompressor(level=config.ZSTD_LEVEL)   # single thread
ZSTD_DECOMPRESSOR = zstandard.ZstdDecompressor()

COMPRESS = {
    # mtime=0 so the output does not depend on the current time
    "gzip": lambda data: gzip.compress(data, compresslevel=config.GZIP_LEVEL, mtime=0),
    "zstd": lambda data: ZSTD_COMPRESSOR.compress(data),
}
DECOMPRESS = {
    "gzip": gzip.decompress,
    "zstd": ZSTD_DECOMPRESSOR.decompress,
}


def cpu_name():
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown (write it by hand)"


def ram_size():
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal"):
                kib = int(line.split()[1])
                return f"{kib / 1024 ** 2:.1f} GiB"
    except (OSError, ValueError):
        pass
    return "unknown (write it by hand)"


def write_environment(path):
    lines = [
        f"date: {datetime.now().isoformat(timespec='seconds')}",
        f"python: {platform.python_version()}",
        f"os: {platform.platform()}",
        f"cpu: {cpu_name()}",
        f"zlib (gzip): {zlib.ZLIB_RUNTIME_VERSION}, level {config.GZIP_LEVEL}",
        f"zstd: libzstd {'.'.join(map(str, zstandard.ZSTD_VERSION))} "
        f"(python-zstandard {zstandard.__version__}), level {config.ZSTD_LEVEL}, single thread",
        f"ram: {ram_size()}",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="Measure compression ratio and time.")
    ap.add_argument("--run", required=True, help="run name, e.g. pilot or final")
    args = ap.parse_args()

    run_dir = config.RUNS_DIR / args.run
    manifest_path = run_dir / "manifest.csv"
    if not manifest_path.exists():
        sys.exit(f"{manifest_path} not found. Run 01_select_sample.py first.")
    with open(manifest_path, newline="", encoding="utf-8") as f:
        manifest = list(csv.DictReader(f))

    # Random order of the two algorithms for each file (fixed seed -> reproducible).
    rng = random.Random(f"{config.SEED}-order")
    results = []
    for i, row in enumerate(manifest, 1):
        data = (run_dir / row["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            sys.exit(f"ERROR: {row['id']} ({row['file']}) has changed: SHA-256 does not match.")

        order = ["gzip", "zstd"]
        rng.shuffle(order)
        out = {"id": row["id"], "type": row["type"], "format": row["format"],
               "size_bytes": len(data), "first_algo": order[0]}
        for algo in order:
            t0 = time.perf_counter_ns()
            compressed = COMPRESS[algo](data)
            t1 = time.perf_counter_ns()
            if DECOMPRESS[algo](compressed) != data:
                sys.exit(f"ERROR: {algo} round-trip failed for {row['id']}.")
            out[f"size_{algo}"] = len(compressed)
            out[f"ratio_{algo}"] = f"{len(compressed) / len(data):.6f}"
            out[f"time_{algo}"] = f"{(t1 - t0) / 1e9:.9f}"
        results.append(out)
        print(f"[{i:3d}/{len(manifest)}] {row['id']}: gzip {out['ratio_gzip']}  "
              f"zstd {out['ratio_zstd']}")

    with open(run_dir / "results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        w.writeheader()
        w.writerows(results)

    print(f"\nData written to {run_dir / 'results.csv'}\n\nEnvironment:")
    write_environment(run_dir / "environment.txt")


if __name__ == "__main__":
    main()
