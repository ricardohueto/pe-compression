"""
config.py - Every fixed decision of the study lives here.
Change values ONLY before selecting the final sample, and copy them to the protocol.
"""
from pathlib import Path

# --- Paths -----------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent      # project root
RUNS_DIR = ROOT / "runs"                           # one sub-folder per run (pilot, final)
KERNEL_DIR = ROOT / "external" / "linux"           # local clone of the Linux kernel

# --- Sampling --------------------------------------------------------------
SEED = 20261106                    # random seed of the final run (write it in the protocol)
N_PER_TYPE = 50                    # files per type in the final run
MIN_BYTES = 1024                   # exclusion: smaller than 1 KB
MAX_BYTES = 50 * 1024 * 1024       # exclusion: larger than 50 MB
TYPES = ("text", "code", "image")

# --- Compression -----------------------------------------------------------
GZIP_LEVEL = 6                     # default level of the gzip tool
ZSTD_LEVEL = 3                     # default level of the zstd tool

# --- Sources ---------------------------------------------------------------
GUTENBERG_CATALOG_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
GUTENBERG_MIRROR = "https://aleph.pglaf.org"       # official mirror (bulk access allowed)
GUTENBERG_LANGUAGE = "en"                          # books whose only language is this one

KERNEL_TAG = "v6.12"                               # Linux release (LTS)

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
IMAGE_MIMES = {"image/jpeg": "jpg", "image/png": "png"}

# --- Network etiquette -----------------------------------------------------
# Wikimedia requires a descriptive User-Agent with a contact address.
USER_AGENT = "PE-FIB-compression-study/1.0 (UPC student project; contact: ricardo.hueto@estudiantat.upc.edu)"
REQUEST_DELAY_S = 2.0              # pause before every download
