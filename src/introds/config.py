"""Shared configuration. Secrets are resolved in order: environment variable -> .env -> Colab Secrets."""

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def get_secret(name):
    value = os.getenv(name)
    if value is not None:  # set, possibly empty on purpose (e.g. no key): never ask Colab
        return value or None
    try:  # On Colab: add the secret in the left sidebar (key icon)
        from google.colab import userdata
    except ImportError:
        return None
    try:
        return userdata.get(name)
    except (userdata.SecretNotFoundError, userdata.NotebookAccessError):
        return None


S2_API_KEY = get_secret("S2_API_KEY")

DATA_DIR = Path(os.getenv("INTRODS_DATA_DIR", REPO_ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"  # raw/<yymm-nnnnn>/v<k>/<original path inside the tarball>
DB_PATH = DATA_DIR / "crawl.sqlite"
EXPORT_DIR = DATA_DIR / "hf"  # Hugging Face dataset layout: hf/data/<table>/*.parquet

USER_AGENT = os.getenv(
    "INTRODS_USER_AGENT",
    "introDS-group15-crawler/0.1 (HCMUS course project)",
)

ARXIV_SRC_URL = "https://export.arxiv.org/src"
S2_BATCH_URL = "https://api.semanticscholar.org/graph/v1/paper/batch"

# Minimum spacing (seconds) between two requests to the same host
ARXIV_DELAY = 3.0
S2_DELAY = 1.05 if S2_API_KEY else 3.05  # without a key: 100 requests / 5 minutes

MAX_ATTEMPTS = 3  # per version / per paper before an item stays 'failed'
