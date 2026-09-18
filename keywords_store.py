import json
import os
from pathlib import Path

from config import TITLE_KEYWORDS, TITLE_EXCLUDE_KEYWORDS

DATA_DIR = Path(os.getenv("DATA_DIR", Path(__file__).parent))
KEYWORDS_FILE = DATA_DIR / "keywords.json"


def _uses_dynamodb() -> bool:
    return os.getenv("DATABASE_BACKEND", "sqlite").strip().lower() == "dynamodb"


def get_keywords() -> dict:
    """Return current keywords, reading from keywords.json if it exists."""
    defaults = {
        "title_keywords": list(TITLE_KEYWORDS),
        "title_exclude_keywords": list(TITLE_EXCLUDE_KEYWORDS),
    }
    if _uses_dynamodb():
        from dynamodb_store import get_keywords as get_dynamodb_keywords

        return get_dynamodb_keywords(defaults)

    if KEYWORDS_FILE.exists():
        try:
            data = json.loads(KEYWORDS_FILE.read_text())
            return {
                "title_keywords": data.get("title_keywords", list(TITLE_KEYWORDS)),
                "title_exclude_keywords": data.get("title_exclude_keywords", list(TITLE_EXCLUDE_KEYWORDS)),
            }
        except Exception:
            pass
    return defaults


def save_keywords(title_keywords: list, title_exclude_keywords: list):
    """Persist keywords to keywords.json."""
    if _uses_dynamodb():
        from dynamodb_store import save_keywords as save_dynamodb_keywords

        save_dynamodb_keywords(title_keywords, title_exclude_keywords)
        return

    KEYWORDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEYWORDS_FILE.write_text(json.dumps({
        "title_keywords": title_keywords,
        "title_exclude_keywords": title_exclude_keywords,
    }, indent=2))
