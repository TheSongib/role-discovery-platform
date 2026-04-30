import json
from pathlib import Path

from config import TITLE_KEYWORDS, TITLE_EXCLUDE_KEYWORDS

KEYWORDS_FILE = Path(__file__).parent / "keywords.json"


def get_keywords() -> dict:
    """Return current keywords, reading from keywords.json if it exists."""
    if KEYWORDS_FILE.exists():
        try:
            data = json.loads(KEYWORDS_FILE.read_text())
            return {
                "title_keywords": data.get("title_keywords", list(TITLE_KEYWORDS)),
                "title_exclude_keywords": data.get("title_exclude_keywords", list(TITLE_EXCLUDE_KEYWORDS)),
            }
        except Exception:
            pass
    return {
        "title_keywords": list(TITLE_KEYWORDS),
        "title_exclude_keywords": list(TITLE_EXCLUDE_KEYWORDS),
    }


def save_keywords(title_keywords: list, title_exclude_keywords: list):
    """Persist keywords to keywords.json."""
    KEYWORDS_FILE.write_text(json.dumps({
        "title_keywords": title_keywords,
        "title_exclude_keywords": title_exclude_keywords,
    }, indent=2))
