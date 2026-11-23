"""AI-Cleanup: strip AI fingerprints (invisible characters, chatbot artifacts, metadata) from files."""
__version__ = "1.0.0"

from .report import Options, Report  # noqa: E402,F401
from .text import clean_text, clean_markup, reveal  # noqa: E402,F401
from .engine import clean_file  # noqa: E402,F401
