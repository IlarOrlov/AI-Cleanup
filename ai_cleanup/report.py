"""Options and reporting shared by every cleaner."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Options:
    invisible: bool = True       # zero-width, bidi, tag, variation-selector, control chars
    spaces: bool = True          # exotic spaces (NBSP, thin, narrow, ideographic...) -> plain space
    typography: bool = True      # em/en dashes, smart quotes, ellipsis -> ASCII
    citations: bool = True       # chatbot citation/reference artifacts and tracking params
    metadata: bool = True        # file metadata (EXIF/XMP/C2PA/doc properties/PDF info...)
    symbols: bool = False        # decorative emoji/icons typical of chatbot output (✅ 🚀 ⓘ ✨ ...)
    preserve_legit: bool = True  # keep ZWJ/ZWNJ/VS where emoji or Indic/Arabic scripts need them
    keep_icc: bool = True        # keep image colour profile (affects colours, not provenance)


@dataclass
class Report:
    changes: Counter = field(default_factory=Counter)
    notes: list[str] = field(default_factory=list)

    def add(self, key: str, n: int = 1) -> None:
        if n:
            self.changes[key] += n

    def note(self, msg: str) -> None:
        if msg not in self.notes:
            self.notes.append(msg)

    def merge(self, other: "Report") -> None:
        self.changes.update(other.changes)
        for n in other.notes:
            self.note(n)

    @property
    def total(self) -> int:
        return sum(self.changes.values())

    def summary(self) -> str:
        if not self.changes:
            return "nothing found"
        return ", ".join(f"{k}: {v}" for k, v in self.changes.most_common())
