"""Text cleaning: invisible characters, exotic spaces, AI typography and chatbot artifacts."""
from __future__ import annotations

import re
import unicodedata

from .report import Options, Report

# --------------------------------------------------------------------------- character tables

ZERO_WIDTH = {
    0x200B: "ZERO WIDTH SPACE",
    0x200C: "ZERO WIDTH NON-JOINER",
    0x200D: "ZERO WIDTH JOINER",
    0x2060: "WORD JOINER",
    0x2061: "FUNCTION APPLICATION",
    0x2062: "INVISIBLE TIMES",
    0x2063: "INVISIBLE SEPARATOR",
    0x2064: "INVISIBLE PLUS",
    0xFEFF: "ZERO WIDTH NO-BREAK SPACE / BOM",
    0x180E: "MONGOLIAN VOWEL SEPARATOR",
    0x00AD: "SOFT HYPHEN",
    0x034F: "COMBINING GRAPHEME JOINER",
    0x115F: "HANGUL CHOSEONG FILLER",
    0x1160: "HANGUL JUNGSEONG FILLER",
    0x3164: "HANGUL FILLER",
    0xFFA0: "HALFWIDTH HANGUL FILLER",
    0x17B4: "KHMER VOWEL INHERENT AQ",
    0x17B5: "KHMER VOWEL INHERENT AA",
    0x2800: "BRAILLE PATTERN BLANK",
    0xFFFC: "OBJECT REPLACEMENT CHARACTER",
}
BIDI = {0x200E, 0x200F, 0x061C, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}
# Deprecated format chars (inhibit/activate symmetric swapping, etc.)
DEPRECATED_FORMAT = set(range(0x206A, 0x2070))
SHORTHAND_FORMAT = set(range(0x1BCA0, 0x1BCA4))
LINE_SEPARATORS = {0x2028: "\n", 0x2029: "\n"}

SPACES = {0x00A0, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000, 0x1680}

# Legitimate Cf chars that must never be touched by the catch-all
_CF_KEEP = {*range(0x0600, 0x0606), 0x06DD, 0x070F, 0x0890, 0x0891, 0x08E2, 0x110BD, 0x110CD,
            *range(0x13430, 0x13456), *range(0x1D173, 0x1D17B)}

TYPO = {
    "\u2014": "em dash", "\u2015": "em dash", "\u2013": "en dash",
    "\u2010": "hyphen variant", "\u2011": "hyphen variant", "\u2012": "hyphen variant",
    "\u2212": "hyphen variant", "\u201C": "smart quote", "\u201D": "smart quote",
    "\u201E": "smart quote", "\u201F": "smart quote", "\u2018": "smart quote",
    "\u2019": "smart quote", "\u201A": "smart quote", "\u201B": "smart quote",
    "\u2026": "ellipsis",
}


def _is_emoji_like(cp: int) -> bool:
    return (cp >= 0x1F000 and cp < 0x1FB00) or 0x2600 <= cp <= 0x27BF or 0x2300 <= cp <= 0x23FF \
        or 0x2B00 <= cp <= 0x2BFF or 0x2190 <= cp <= 0x21FF or cp in (0x00A9, 0x00AE, 0x203C,
                                                                     0x2049, 0x2122, 0x2139, 0x3030, 0x303D)


def _is_joining_script(cp: int) -> bool:
    """Scripts where ZWJ/ZWNJ carry real meaning (Arabic, Persian, Indic, Sinhala...)."""
    return 0x0600 <= cp <= 0x08FF or 0x0900 <= cp <= 0x0DFF or 0xFB50 <= cp <= 0xFDFF \
        or 0xFE70 <= cp <= 0xFEFE or 0x1000 <= cp <= 0x109F or 0x1780 <= cp <= 0x17FF


def classify(ch: str) -> str | None:
    """Return the removal category of a character, or None if it is a normal character."""
    cp = ord(ch)
    if cp in ZERO_WIDTH:
        return "zero-width/invisible"
    if cp in BIDI:
        return "bidi control"
    if 0xE0000 <= cp <= 0xE007F:
        return "unicode tag (hidden text)"
    if 0xFE00 <= cp <= 0xFE0F or 0xE0100 <= cp <= 0xE01EF:
        return "variation selector"
    if cp in DEPRECATED_FORMAT or cp in SHORTHAND_FORMAT:
        return "zero-width/invisible"
    if (cp < 0x20 and ch not in "\t\n\r\f") or 0x7F <= cp <= 0x9F:
        return "control character"
    if 0xE200 <= cp <= 0xE2FF:
        return "chatbot citation marker"
    if cp not in _CF_KEEP and unicodedata.category(ch) == "Cf":
        return "zero-width/invisible"
    return None


def char_name(ch: str) -> str:
    cp = ord(ch)
    if cp in ZERO_WIDTH:
        return ZERO_WIDTH[cp]
    if 0xE0000 <= cp <= 0xE007F:
        inner = cp - 0xE0000
        return f"TAG {chr(inner)!r}" if 0x20 <= inner < 0x7F else "TAG"
    if 0xE200 <= cp <= 0xE2FF:
        return f"PRIVATE-USE U+{cp:04X}"
    return unicodedata.name(ch, f"U+{cp:04X}")


# --------------------------------------------------------------------------- chatbot artifacts

_AI_UTM = r"(?:chatgpt\.com|openai(?:\.com)?|perplexity(?:\.ai)?|copilot(?:\.microsoft)?\.com|claude\.ai|gemini(?:\.google\.com)?|bard|you\.com|phind(?:\.com)?)"
CITATION_PATTERNS: list[tuple[str, re.Pattern]] = [
    # ChatGPT private-use citation blocks:  \ue200cite\ue202turn0search3\ue201
    ("chatbot citation", re.compile(r"[ \t]*\ue200[^\ue201]{0,400}\ue201")),
    # ChatGPT file/web citations rendered as  \u30104:0\u2020source\u3011  or  \u301012\u2020L30-L45\u3011
    ("chatbot citation", re.compile(r"[ \t]*\u3010\d+(?::\d+)?\u2020[^\u3011\n]{0,200}\u3011")),
    # contentReference[oaicite:3]{index=3}
    ("chatbot citation", re.compile(r"[ \t]*:?contentReference\[oaicite:\d+\](?:\{index=\d+\})?")),
    ("chatbot citation", re.compile(r"[ \t]*\[oaicite:\d+\]")),
    # leftovers once the private-use markers are gone: citeturn0search0turn1news2
    ("chatbot citation", re.compile(r"[ \t]*\b(?:cite|filecite|navlist|image_group|entity)(?:turn\d+[a-z]+\d+)+\b")),
    ("chatbot citation", re.compile(r"\bturn\d+(?:search|news|view|fetch|file|image|forecast|finance|sports)\d+\b")),
    # Grok inline render tags
    ("chatbot citation", re.compile(r"<grok:render\b[^>]*>.*?</grok:render>", re.S)),
    ("chatbot citation", re.compile(r"<grok:render\b[^>]*/>")),
    # Perplexity / generic numbered footnote markers glued to words:  text[1][2]
    # (intentionally NOT removed - too many legitimate uses)
]
UTM_PATTERNS = [
    re.compile(r"\?utm_source=" + _AI_UTM + r"&"),
    re.compile(r"\?utm_source=" + _AI_UTM + r"(?=[.,;:!?]*(?:[\s)\]\"'<>`#]|$))"),
    re.compile(r"&(?:amp;)?utm_source=" + _AI_UTM + r"(?=[.,;:!?]*(?:[&\s)\]\"'<>`#]|$))"),
]


def remove_citations(text: str, report: Report) -> str:
    for label, pat in CITATION_PATTERNS:
        text, n = pat.subn("", text)
        report.add(label, n)
    text, n = UTM_PATTERNS[0].subn("?", text)
    report.add("AI tracking param in URL", n)
    for pat in UTM_PATTERNS[1:]:
        text, n = pat.subn("", text)
        report.add("AI tracking param in URL", n)
    return text


# --------------------------------------------------------------------------- invisible chars

_FLAG_TAG_SEQ = re.compile("\U0001F3F4[\U000E0020-\U000E007E]{1,6}\U000E007F")


def remove_invisible(text: str, report: Report, preserve_legit: bool = True,
                     spaces: bool = True) -> str:
    protected: set[int] = set()
    if preserve_legit:
        for m in _FLAG_TAG_SEQ.finditer(text):
            protected.update(range(m.start(), m.end()))

    out: list[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        cp = ord(ch)
        if cp in LINE_SEPARATORS:
            out.append(LINE_SEPARATORS[cp])
            report.add("unicode line separator")
            continue
        if spaces and cp in SPACES:
            out.append(" ")
            report.add("non-standard space")
            continue
        cat = classify(ch)
        if cat is None or i in protected:
            out.append(ch)
            continue
        if preserve_legit and cat in ("zero-width/invisible", "variation selector"):
            prev = ord(out[-1]) if out else 0
            nxt = ord(text[i + 1]) if i + 1 < n else 0
            if cp == 0x200D and (_is_emoji_like(prev) or prev in (0xFE0F, *range(0x1F3FB, 0x1F400))) \
                    and _is_emoji_like(nxt):
                out.append(ch)
                continue
            if cp in (0x200C, 0x200D) and _is_joining_script(prev) and _is_joining_script(nxt):
                out.append(ch)
                continue
            if cp in (0xFE0E, 0xFE0F) and prev not in (0xFE0E, 0xFE0F) and (
                    _is_emoji_like(prev) or chr(prev) in "0123456789#*"):
                out.append(ch)
                continue
        report.add(cat)
    return "".join(out)


# --------------------------------------------------------------------------- typography

def normalize_typography(text: str, report: Report, quotes: bool = True) -> str:
    def count(chars: str, label: str) -> None:
        report.add(label, sum(text.count(c) for c in chars))

    count("\u2014\u2015", "em dash")
    text = re.sub(r"[ \t]*[\u2014\u2015][ \t]*", " - ", text)
    text = re.sub(r"(?m)^ - ", "- ", text)
    text = re.sub(r"(?m) - $", " -", text)

    count("\u2013", "en dash")
    text = re.sub(r"(\w)[ \t]*\u2013[ \t]*(\d)", r"\1-\2", text)
    text = re.sub(r"[ \t]*\u2013[ \t]*", " - ", text)

    count("\u2010\u2011\u2012\u2212", "hyphen variant")
    text = re.sub("[\u2010\u2011\u2012\u2212]", "-", text)

    count("\u2026", "ellipsis")
    text = text.replace("\u2026", "...")

    if quotes:
        count("\u201C\u201D\u201E\u201F\u2018\u2019\u201A\u201B", "smart quote")
        text = re.sub("[\u201C\u201D\u201E\u201F]", '"', text)
        text = re.sub("[\u2018\u2019\u201A\u201B]", "'", text)
    return text


# --------------------------------------------------------------------------- decorative symbols

# Pictographs chatbots sprinkle over headings/bullets. Ballot boxes (\u2610\u2611\u2612), arrows and
# check marks used as plain glyphs in forms are deliberately NOT included.
_DECOR = re.compile(
    "(?:[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF]|[\u2705\u274C\u274E\u2728\u2B50\u2B55\u26A0"
    "\u26A1\u2753\u2754\u2755\u2757\u203C\u2049\u24D8\u2139\u27A1\u2934\u2935\u23F0\u23F3\u231B"
    "\u2600-\u2609\u260E-\u2611\u2613-\u2614\u2618-\u26FF\u2700-\u2704\u2706-\u2713\u2715-\u2727"
    "\u2729-\u274B\u274D\u274F-\u2752\u2756\u2758-\u27BF])"
    "[\uFE0E\uFE0F\U0001F3FB-\U0001F3FF\u20E3]*(?:\u200D\\S\uFE0F?)*[ \t]?"
)
_BALLOT = "\u2610\u2611\u2612"


def remove_symbols(text: str, report: Report) -> str:
    def repl(m: re.Match) -> str:
        if m.group(0)[0] in _BALLOT:
            return m.group(0)
        report.add("decorative symbol/emoji")
        return ""
    return _DECOR.sub(repl, text)


# --------------------------------------------------------------------------- public API

def clean_text(text: str, opts: Options | None = None, report: Report | None = None,
               profile: str = "prose") -> tuple[str, Report]:
    """Clean a plain string.

    profile: "prose" (txt/md: everything), "code" (code/data files: quotes are left alone
    because swapping them could break string literals), "segment" (text node inside markup).
    """
    opts = opts or Options()
    report = report if report is not None else Report()
    if opts.citations:
        text = remove_citations(text, report)
    if opts.invisible or opts.spaces:
        text = _invisible_pass(text, opts, report)
    if opts.symbols:
        text = remove_symbols(text, report)
    if opts.typography:
        text = normalize_typography(text, report, quotes=profile != "code")
    return text, report


def _invisible_pass(text: str, opts: Options, report: Report) -> str:
    if opts.invisible:
        return remove_invisible(text, report, opts.preserve_legit, spaces=opts.spaces)
    # spaces only
    out = []
    for ch in text:
        if ord(ch) in SPACES:
            out.append(" ")
            report.add("non-standard space")
        else:
            out.append(ch)
    return "".join(out)


# ---- markup (HTML / XML / SVG / Office XML) -------------------------------------------------

_NUMREF = re.compile(r"&#(x[0-9a-fA-F]+|\d+);")
_SCRIPT_STYLE = re.compile(r"(<(script|style)\b[^>]*>.*?</\2\s*>)", re.S | re.I)
_TEXT_NODE = re.compile(r">([^<]+)<")
_CHATGPT_ATTRS = re.compile(r'\s+data-(?:start|end|is-last-node|is-only-node|pm-slice)="[^"]*"')


def _decode_suspicious_refs(xml: str) -> str:
    """Turn numeric char refs of invisible/space chars into literals so they get cleaned."""
    def repl(m: re.Match) -> str:
        v = m.group(1)
        try:
            cp = int(v[1:], 16) if v[0] in "xX" else int(v)
            ch = chr(cp)
        except (ValueError, OverflowError):
            return m.group(0)
        if cp in SPACES or cp in LINE_SEPARATORS or (classify(ch) and cp >= 0x7F):
            return ch
        return m.group(0)
    return _NUMREF.sub(repl, xml)


def clean_markup(xml: str, opts: Options | None = None, report: Report | None = None,
                 html: bool = False) -> tuple[str, Report]:
    """Clean markup while leaving tags/attributes structurally valid.

    Invisible chars are removed everywhere (always safe); typography and citation fixes
    are applied only to text nodes (outside <script>/<style>), so quotes in attributes
    can never break the document.
    """
    opts = opts or Options()
    report = report if report is not None else Report()
    if opts.invisible or opts.spaces:
        xml = _decode_suspicious_refs(xml)
    if html and opts.citations:
        xml, n = _CHATGPT_ATTRS.subn("", xml)
        report.add("chat-UI copy attribute", n)

    seg_opts = Options(**{**opts.__dict__, "invisible": False, "spaces": False})
    # ZWJ inside emoji sequences must still be visible to the symbol pass
    if opts.symbols:
        xml = remove_symbols_in_nodes(xml, report)
        seg_opts.symbols = False

    def fix_nodes(chunk: str) -> str:
        return _TEXT_NODE.sub(lambda m: ">" + clean_text(m.group(1), seg_opts, report, "segment")[0] + "<",
                              chunk)

    parts = _SCRIPT_STYLE.split(xml) if html else [xml]
    out = []
    skip = 0
    for idx, part in enumerate(parts):
        if skip:
            skip -= 1
            continue
        if html and idx % 3 == 1:          # captured <script>/<style> block + tag-name group
            out.append(part)
            skip = 1
            continue
        out.append(fix_nodes(part))
    xml = "".join(out)

    if opts.invisible or opts.spaces:
        xml = _invisible_pass(xml, opts, report)
    return xml, report


def remove_symbols_in_nodes(xml: str, report: Report) -> str:
    return _TEXT_NODE.sub(lambda m: ">" + remove_symbols(m.group(1), report) + "<", xml)


def clean_rtf(rtf: str, opts: Options | None = None, report: Report | None = None) -> tuple[str, Report]:
    """RTF stores non-ASCII as \\uN? escapes; drop the ones that encode invisible chars."""
    opts = opts or Options()
    report = report if report is not None else Report()

    def repl(m: re.Match) -> str:
        cp = int(m.group(1))
        if cp < 0:
            cp += 65536
        ch = chr(cp)
        if opts.invisible and classify(ch):
            report.add(classify(ch))
            return ""
        if opts.spaces and cp in SPACES:
            report.add("non-standard space")
            return " "
        if opts.typography and ch in TYPO:
            fixed = normalize_typography(ch, Report())
            report.add(TYPO[ch])
            return fixed.strip() or fixed
        return m.group(0)

    rtf = re.sub(r"\\u(-?\d+) ?(?:\?|\\'[0-9a-fA-F]{2})?", repl, rtf)
    rtf, _ = clean_text(rtf, opts, report, "code")
    return rtf, report


def reveal(text: str) -> str:
    """Return text with every hidden character made visible as ⟦NAME⟧ (for inspection)."""
    out = []
    for ch in text:
        cp = ord(ch)
        if classify(ch) or cp in SPACES or cp in LINE_SEPARATORS:
            out.append(f"⟦{char_name(ch)}⟧")
            if cp in LINE_SEPARATORS:
                out.append("\n")
        else:
            out.append(ch)
    return "".join(out)
