"""
Pure text helpers of the VoxCPM2 voice service (no torch, no model: tested in CI).

- speak(): French speech normalisation, applied to what the voice says only (captions keep
  the script as written): "308 kcal" -> "trois cent huit calories", "21 h" -> "vingt et une
  heures", "macrobody.fr" -> "Macro Body point f r", "MacroBody" -> "Macro Body".
- take_text(): the script lines joined into ONE take (a line break is a sentence break).
- score(): how close a Whisper transcript is to the text the voice had to say (0..1).
- line_spans(): Whisper word timings grouped into one span per script line.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Dict, List, Sequence, Tuple

from num2words import num2words

M, F = "m", "f"
# unit as written -> (spoken singular, gender, plural). "kcal" is said "calories": that is
# what French speakers say, and the viewer reads kcal on screen anyway.
UNITS: Dict[str, Tuple[str, str, str]] = {
    "kcal": ("calorie", F, "calories"), "cal": ("calorie", F, "calories"),
    "kg": ("kilo", M, "kilos"), "mg": ("milligramme", M, "milligrammes"),
    "g": ("gramme", M, "grammes"), "ml": ("millilitre", M, "millilitres"),
    "cl": ("centilitre", M, "centilitres"), "l": ("litre", M, "litres"),
    "km": ("kilomètre", M, "kilomètres"), "min": ("minute", F, "minutes"),
    "h": ("heure", F, "heures"), "%": ("pour cent", M, "pour cent"),
    "€": ("euro", M, "euros"),
}
TLDS = {"fr": "f r", "io": "i o", "com": "com", "net": "net", "org": "org", "app": "app"}
_UNIT_RE = "|".join(sorted((re.escape(u) for u in UNITS), key=len, reverse=True))
_SEP = "[   ]"  # French thousands: space, no-break space, narrow no-break space
_NUM = rf"(\d{{1,3}}(?:{_SEP}\d{{3}})+(?!\d)|\d+)(?:[,.](\d+))?"
_DOMAIN = re.compile(rf"\b([a-z0-9-]+)\.({'|'.join(TLDS)})\b", re.I)
_BRAND = re.compile(r"\bmacro\s?body\b", re.I)
_TIME = re.compile(r"(?<![\d,.])(\d{1,2})\s?h\s?(\d{2})(?!\d)")
_ORDINAL = re.compile(r"(?<![\d,.])(\d+)(er|re|ère|e|ème)\b")
_AMOUNT = re.compile(rf"(?<![\w,.]){_NUM}(?:{_SEP}?({_UNIT_RE})(?![\w'’]))?")


def number(n: int, feminine: bool = False) -> str:
    words = num2words(n, lang="fr")
    if feminine and (words == "un" or words.endswith((" un", "-un"))):
        words += "e"
    return words


def _amount(m: re.Match) -> str:
    whole, frac, unit = m.group(1), m.group(2), m.group(3)
    value = int(re.sub(_SEP, "", whole))
    spoken_unit, gender, plural = UNITS.get(unit or "", ("", M, ""))
    out = number(value, feminine=gender == F and not frac)
    if frac:  # "1,5" -> "un virgule cinq"; leading zeros said one by one
        zeros = len(frac) - len(frac.lstrip("0"))
        tail = [number(0)] * zeros + ([number(int(frac))] if frac.strip("0") else [])
        out += " virgule " + " ".join(tail or [number(0)])
    if unit:
        out += " " + (plural if value >= 2 else spoken_unit)
    return out


def _ordinal(m: re.Match) -> str:
    if m.group(1) == "1" and m.group(2) in ("re", "ère"):
        return "première"
    return num2words(int(m.group(1)), to="ordinal", lang="fr")


def speak(text: str) -> str:
    """The text as the voice should say it (French)."""
    text = _DOMAIN.sub(lambda m: f"{m.group(1)} point {TLDS[m.group(2).lower()]}", text)
    text = _BRAND.sub("Macro Body", text)
    text = _TIME.sub(lambda m: f"{number(int(m.group(1)), True)} "
                               f"{'heures' if int(m.group(1)) >= 2 else 'heure'}"
                               + (f" {number(int(m.group(2)))}" if int(m.group(2)) else ""),
                     text)
    text = _ORDINAL.sub(_ordinal, text)
    return _AMOUNT.sub(_amount, text)


def unbracket(line: str) -> str:
    """What is said of a line with brackets: the bracketed part is shown (captions), never
    said: « (rires) Tu connais » → « Tu connais », « soir (vers 21 h). » → « soir. ». A
    stage direction read aloud sounds wrong, and VoxCPM2 reads a bracketed block at the
    start of the text as a voice instruction (a designed voice's style goes there)."""
    if "(" not in line and ")" not in line:
        return line.strip()
    line = re.sub(r"\([^()]*\)", " ", line).replace("(", " ").replace(")", " ")
    line = re.sub(r"\s+([,.!?…:;])", r"\1", " ".join(line.split()))
    line = re.sub(r",(?=[.!?…:;,])", "", line)
    return line.strip(" ,;:")


def take_text(lines: Sequence[str]) -> str:
    """One take for the whole script: lines joined, each a capitalised, closed sentence,
    bracketed parts left unsaid (unbracket). (The capital matters: VoxCPM2 reads the card
    text + this text as one string, and "…vraies.vingt" came out as « point vingt ».)"""
    out = []
    for line in (unbracket(raw) for raw in lines):
        if line:
            line = line[0].upper() + line[1:]
            out.append(line if line[-1] in ".!?…:;," else line + ".")
    return " ".join(out)


def tokens(text: str) -> List[str]:
    """Words for comparing speech: normalised the same way, lower case, no accents."""
    plain = unicodedata.normalize("NFKD", speak(text).lower())
    return re.findall(r"[a-z0-9]+", "".join(c for c in plain if not unicodedata.combining(c)))


def score(expected: str, heard: str) -> float:
    """Similarity of the words said to the words meant, 0..1 (difflib ratio)."""
    return difflib.SequenceMatcher(None, tokens(expected), tokens(heard), autojunk=False).ratio()


def _size(text: str) -> int:
    return sum(len(t) for t in tokens(text))


def line_spans(words: Sequence[Dict], lines: Sequence[str]) -> List[Dict]:
    """One {text, start_s, end_s} per script line (text as written), from Whisper's word
    timings. Words are matched to lines by their position in the spoken letters, both sides
    normalised by speak(), so "308" heard and "trois cent huit" said weigh the same. The studio
    (src/studio/tts.py group_words_into_lines) maps these spans back 1:1, since each carries
    its line's own text. A line that got no word sits at the previous end."""
    bounds, acc = [], 0
    for line in lines:
        acc += _size(line)
        bounds.append(acc)
    total_line = acc or 1
    total_word = sum(_size(w["text"]) for w in words) or 1
    groups: List[List[Dict]] = [[] for _ in lines]
    pos, i = 0, 0
    for w in words:
        mid = (pos + _size(w["text"]) / 2) * total_line / total_word
        pos += _size(w["text"])
        while i < len(lines) - 1 and mid >= bounds[i]:
            i += 1
        groups[i].append(w)
    out, prev_end = [], 0.0
    for line, group in zip(lines, groups):
        if group:
            start, prev_end = group[0]["start_s"], group[-1]["end_s"]
        else:
            start = prev_end
        out.append({"text": line, "start_s": round(start, 3), "end_s": round(prev_end, 3)})
    return out
