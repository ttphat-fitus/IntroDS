import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")


def get_secret(name):
    value = os.getenv(name)
    if value:
        return value
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
RAW_DIR = (
    DATA_DIR / "raw"
)  # data/raw/<yymm-nnnnn>/v<k>/<original path inside the tarball>
DB_PATH = DATA_DIR / "crawl.sqlite"

USER_AGENT = os.getenv(
    "INTRODS_USER_AGENT",
    "introDS-group15-crawler/0.1 (HCMUS course project)",
)

# Minimum spacing (seconds) between two requests to the same host
ARXIV_DELAY = 3.0
S2_DELAY = 1.05 if S2_API_KEY else 3.05  # without a key: 100 requests / 5 minutes
