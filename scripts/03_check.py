#!/usr/bin/env python3
"""
03_check.py - Checks that scripts 01 and 02 worked and prints a summary.

    python scripts/03_check.py --run final

ERROR   = something is wrong, the data must not be used as they are.
WARNING = unusual value; look at that file by hand, it may still be correct.
"""
import argparse
import csv
import hashlib
import statistics
import sys

import config

# Typical ratio ranges; outside them we warn (not an error).
EXPECTED = {"text": (0.15, 0.60), "code": (0.10, 0.60), "image": (0.85, 1.05)}


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser(description="Check a run.")
    ap.add_argument("--run", required=True)
    ap.add_argument("--n", type=int, default=config.N_PER_TYPE, help="expected files per type")
    args = ap.parse_args()

    run_dir = config.RUNS_DIR / args.run
    errors, warnings = [], []

    # --- 1. Manifest ---------------------------------------------------------
    if not (run_dir / "manifest.csv").exists():
        sys.exit(f"{run_dir}/manifest.csv not found: run 01_select_sample.py first.")
    manifest = read_csv(run_dir / "manifest.csv")
    for t in config.TYPES:
        k = sum(1 for r in manifest if r["type"] == t)
        if k != args.n:
            errors.append(f"manifest: {k} files of type {t}, expected {args.n}")
    ids = [r["id"] for r in manifest]
    if len(ids) != len(set(ids)):
        errors.append("manifest: repeated ids")
    hashes = [r["sha256"] for r in manifest]
    if len(hashes) != len(set(hashes)):
        errors.append("manifest: two files are identical (same SHA-256)")
    for r in manifest:
        path = run_dir / r["file"]
        if not path.exists():
            errors.append(f"{r['id']}: file missing ({r['file']})")
            continue
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != r["sha256"]:
            errors.append(f"{r['id']}: file changed (SHA-256 mismatch)")
        if not config.MIN_BYTES <= len(data) <= config.MAX_BYTES:
            errors.append(f"{r['id']}: size {len(data)} outside the inclusion range")
    print(f"Manifest: {len(manifest)} files checked.")

    # --- 2. Results ----------------------------------------------------------
    results_path = run_dir / "results.csv"
    if not results_path.exists():
        errors.append("results.csv not found: run 02_measure.py")
        results = []
    else:
        results = read_csv(results_path)
    by_id = {r["id"]: r for r in manifest}
    if results and {r["id"] for r in results} != set(by_id):
        errors.append("results.csv and manifest.csv do not contain the same ids")
    for r in results:
        if any((v or "").strip() == "" for v in r.values()):
            errors.append(f"{r['id']}: empty value in results.csv")
            continue
        size = int(r["size_bytes"])
        m = by_id.get(r["id"])
        if m and size != int(m["size_bytes"]):
            errors.append(f"{r['id']}: size differs from the manifest")
        if m and (r["type"], r["format"]) != (m["type"], m["format"]):
            errors.append(f"{r['id']}: type/format differs from the manifest")
        for algo in ("gzip", "zstd"):
            ratio = float(r[f"ratio_{algo}"])
            if abs(ratio - int(r[f"size_{algo}"]) / size) > 1e-5:
                errors.append(f"{r['id']}: ratio_{algo} does not equal size_{algo}/size_bytes")
            if not 0 < ratio < 1.2:
                errors.append(f"{r['id']}: impossible ratio_{algo} = {ratio}")
            lo, hi = EXPECTED[r["type"]]
            if not lo <= ratio <= hi:
                warnings.append(f"{r['id']}: ratio_{algo} = {ratio:.3f} is unusual for "
                                f"{r['type']} (typical {lo}-{hi})")
            if float(r[f"time_{algo}"]) <= 0:
                errors.append(f"{r['id']}: time_{algo} is not positive")
    print(f"Results:  {len(results)} rows checked.")

    # --- 3. Summary ----------------------------------------------------------
    if results:
        print(f"\n{'type':<6} {'n':>3} {'mean gzip':>10} {'mean zstd':>10} "
              f"{'mean diff':>10} {'zstd better':>12}")
        for t in config.TYPES:
            rows = [r for r in results if r["type"] == t]
            if not rows:
                continue
            g = [float(r["ratio_gzip"]) for r in rows]
            z = [float(r["ratio_zstd"]) for r in rows]
            d = [zi - gi for zi, gi in zip(z, g)]
            better = sum(1 for x in d if x < 0)
            print(f"{t:<6} {len(rows):>3} {statistics.mean(g):>10.4f} {statistics.mean(z):>10.4f} "
                  f"{statistics.mean(d):>+10.4f} {better:>6}/{len(rows)}")
        print("(diff = ratio_zstd - ratio_gzip; negative means zstd compresses more)")

    # --- 4. Verdict ----------------------------------------------------------
    for w in warnings:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:  ", e)
    if errors:
        print(f"\nFAILED: {len(errors)} error(s).")
        sys.exit(1)
    print(f"\nALL CHECKS PASSED ({len(warnings)} warning(s)).")


if __name__ == "__main__":
    main()
