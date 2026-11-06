# gzip vs. zstd: compression ratio study

Probabilitat i Estadística (FIB) – Bloc Transversal.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
git clone --depth 1 --branch v6.12 https://github.com/torvalds/linux.git external/linux
```

Edit `scripts/config.py`: put your e-mail in `USER_AGENT`.

## Run

```bash
# Pilot (12 files, different seed)
python scripts/01_select_sample.py --run pilot --n 4 --seed 1
python scripts/02_measure.py --run pilot
python scripts/03_check.py --run pilot --n 4

# Final sample (150 files) – select ONCE
python scripts/01_select_sample.py --run final
python scripts/02_measure.py --run final
python scripts/03_check.py --run final
```

## Output (`runs/<run>/`)

| File | Content |
|---|---|
| `manifest.csv` | Selected files: id, type, format, source URL/path, size, SHA-256 |
| `skipped.csv` | Candidates drawn but excluded, with the reason |
| `results.csv` | The data: sizes, ratios and times for gzip and zstd |
| `environment.txt` | Software and hardware used |

The sample files themselves are not in the repository; they can be downloaded
again from the sources in `manifest.csv` and verified with their SHA-256.
