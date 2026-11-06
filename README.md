# gzip vs. zstd: compression ratio study

Group project for *Probabilitat i Estadística* (FIB, UPC) – Bloc Transversal.

**Question:** on the same file, does zstd (level 3) compress more than gzip
(level 6)? How large is the difference, and does it depend on the file type
(text, source code, images) and on the file size?

Every file is compressed with both algorithms (paired design). The main
variable is the **compression ratio** = compressed size / original size
(lower is better). Compression time is measured as a secondary variable.

## The two algorithms

Both are *lossless*: decompressing gives back exactly the original bytes.
Both work in two stages: first they replace repeated pieces of data with short
references to an earlier copy ("the same 12 bytes as 300 bytes ago"), then
they encode the result with fewer bits for the most frequent symbols.

| | gzip | zstd (Zstandard) |
|---|---|---|
| Year / author | 1992, Jean-loup Gailly and Mark Adler | 2016, Yann Collet (Facebook / Meta) |
| Format | DEFLATE (also used inside ZIP and PNG) | Zstandard (RFC 8878) |
| Finding repetitions | LZ77 with a **32 KiB** window: it can only refer to the last 32 KiB | LZ77-style matching with a larger window (at level 3 up to **2 MiB**, smaller for small files) |
| Entropy coding | Huffman codes | Huffman (for literals) + Finite State Entropy (tANS, for the references), closer to the theoretical limit |
| Levels | 1–9, default **6** | 1–19 (up to 22), default **3** |
| Design goal | good ratio in 1990s hardware | similar or better ratio than gzip, much faster |

We use the **default level** of each tool, because that is what most users get.

**What we expect:** text and source code have many repetitions, so both
algorithms compress them well, and zstd may compress a bit more thanks to its
larger window and better entropy coding. JPG and PNG images are already
compressed (PNG even uses DEFLATE internally), so they have almost no
redundancy left and both ratios should be close to 1.

Implementation: gzip via Python's `gzip.compress(compresslevel=6, mtime=0)`
(zlib); zstd via `python-zstandard`, `ZstdCompressor(level=3)`, single thread,
no checksum. Files are compressed in memory, and every output is decompressed
and compared with the original.

## Populations and sampling

| Type | Population | Draw |
|---|---|---|
| text | Project Gutenberg books with `Type = Text` and `Language = en` (official catalog `pg_catalog.csv`), downloaded from the mirror `aleph.pglaf.org` | random permutation with the seed |
| code | every `.c` file of the Linux kernel at tag `v6.12` | random permutation with the seed |
| image | JPG and PNG files of Wikimedia Commons | `generator=random` of the Commons API |

- Simple random sample, **50 files per type** in the final run.
- Inclusion: 1 KB ≤ size ≤ 50 MB. A candidate that does not meet the criteria
  (wrong size, no plain-text version, not JPG/PNG) is excluded and replaced by
  the next draw. Every exclusion is written in `skipped.csv`.
- Seed `20261106`, with an independent random generator per type.
- All fixed decisions are in [`scripts/config.py`](scripts/config.py).

## Requirements

- Linux or macOS. On Windows use **WSL** (the kernel has file names Windows rejects).
- Python ≥ 3.10 (tested with 3.12), `git`, ~2 GB of disk for the kernel clone.

```bash
git clone <this repository> && cd pe-compression
python3 -m venv .venv               # or: uv venv .venv
source .venv/bin/activate
pip install -r requirements.txt     # or: uv pip install -r requirements.txt
git clone --depth 1 --branch v6.12 https://github.com/torvalds/linux.git external/linux
```

## Scripts

| Script | What it does |
|---|---|
| `00_fetch_from_manifest.py` | Gets the files of an existing run again (sources in its manifest) and verifies their SHA-256 |
| `01_select_sample.py` | Draws the random sample, downloads it and writes the manifest. Run **once** per run |
| `02_measure.py` | Compresses every file with both algorithms and writes `results.csv` |
| `03_check.py` | Automatic checks and a summary table; ends with `ALL CHECKS PASSED` or `FAILED` |
| `config.py`, `net.py` | Fixed decisions of the study; polite downloads (2 s between requests, retries) |

### Check the pilot (same files, same results)

The sample files are not stored in the repository (they are large and the
images have their own licences), but the manifest records where each file
came from and its SHA-256:

```bash
python scripts/00_fetch_from_manifest.py --run pilot
python scripts/02_measure.py --run pilot --force
python scripts/03_check.py --run pilot --n 4
```

The sizes and ratios in `results.csv` must be identical to the committed ones
(check with `git diff runs/pilot/results.csv`); only the times change, since
they depend on the computer.

### Select a new sample

```bash
python scripts/01_select_sample.py --run final      # ~10-15 min, downloads ~150 files
python scripts/02_measure.py --run final
python scripts/03_check.py --run final
```

`01` refuses to overwrite an existing run, and `02` refuses to overwrite an
existing `results.csv` (times are measured only once), unless `--force` is given.

## Output (`runs/<run>/`)

| File | Content |
|---|---|
| `manifest.csv` | Selected files: `id, type, format, file, source, size_bytes, sha256` |
| `skipped.csv` | Candidates drawn but excluded: `type, source, reason` |
| `results.csv` | **The data:** `id, type, format, size_bytes, size_gzip, size_zstd, ratio_gzip, ratio_zstd, time_gzip, time_zstd, first_algo` |
| `run_info.txt` | Seed, n, date, kernel commit, SHA-256 of the Gutenberg catalog, population sizes |
| `text_population.csv` | The Gutenberg book ids the text sample was drawn from (the catalog grows every day) |
| `environment.txt` | Software and hardware used for the measurements |

In `results.csv` sizes are in bytes and times in seconds. `first_algo` is the
algorithm that was run first for that file (the order is random). The file is
ready for R: `read.csv("runs/final/results.csv")`.

## Pilot

A pilot with 4 files per type (seed 1) was run to test the scripts and to
estimate the variability needed to choose the sample size. Its data are in
[`runs/pilot/`](runs/pilot/). They are only orientative (n = 4).

| Type | mean ratio gzip | mean ratio zstd | mean difference (zstd − gzip) |
|---|---|---|---|
| text | 0.394 | 0.384 | −0.011 |
| code | 0.352 | 0.371 | +0.019 |
| image | 0.992 | 0.994 | +0.002 |

## Limitations

- The Commons `generator=random` is random on the server side: it cannot be
  repeated with the seed (the manifest is what makes it reproducible), and
  MediaWiki's random selection is known to be close to, but not exactly, uniform.
- Gutenberg files include the standard Project Gutenberg header and licence;
  the population is "the files as distributed".
- We measure the libraries (zlib and libzstd, versions in `environment.txt`),
  not the command-line tools. The tools give slightly different sizes: GNU
  `gzip` has its own DEFLATE implementation, and the `zstd` tool adds a 4-byte
  checksum by default and may choose slightly different internal parameters.
  In the pilot the differences were below 0.7 % of the compressed size.

## Repository layout

```
scripts/          the scripts above
runs/pilot/       pilot data (CSV files; the downloaded files are not committed)
runs/final/       final data (once collected)
analysis/         R analysis (to be added)
external/linux/   kernel clone (not committed)
```
