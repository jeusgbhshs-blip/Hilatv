"""Break narration into subtitle lines without splitting a word.

Chinese lines stay within 16 characters. English lines stay within 42.
Timestamps come from N6. A line's clock is the first and last token it covers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from workers.media.packaging import ALIGNMENT_MS, EN_MAX_CHARS, ZH_MAX_CHARS
from workers.nodes.n06_voiceover.schema import WordStamp

_PUNCT = set("，。！？、；：,.!?;:、…")
_SENTENCE_END = set("。！？!?；;")
_UNITS = {"MPa", "kPa", "GPa", "mm", "cm", "kg", "kW", "Hz", "rpm", "ml", "m", "MPa"}
_NUMBER = re.compile(r"(?:[¥￥]\s?)?\d+(?:\.\d+)?(?:\s?[A-Za-z]{1,4})?")
_PHONE = re.compile(r"\d{3,4}-\d{4,8}")


@dataclass
class Atom:
    text: str
    start_s: float
    end_s: float
    break_after: bool = False


@dataclass(frozen=True)
class Line:
    text: str
    start_s: float
    end_s: float


def is_chinese(language: str | None, text: str) -> bool:
    if language:
        return language.lower().split("-", 1)[0] == "zh"
    return any(0x4E00 <= ord(char) <= 0x9FFF for char in text)


def break_lines(
    text: str,
    stamps: list[WordStamp],
    *,
    language: str | None,
    lexicon: list[str],
) -> list[Line]:
    zh = is_chinese(language, text)
    limit = ZH_MAX_CHARS if zh else EN_MAX_CHARS
    lexicon = [word for word in lexicon if 2 <= _length(word, zh=zh) <= limit]
    atoms = segment(text, stamps, lexicon)
    grouped = _pack(atoms, zh=zh, limit=ZH_MAX_CHARS if zh else EN_MAX_CHARS)
    lines: list[Line] = []
    for group in grouped:
        joined = _join(group, zh=zh)
        if not joined.strip():
            continue
        lines.append(Line(text=joined, start_s=group[0].start_s, end_s=group[-1].end_s))
    return lines


def segment(text: str, stamps: list[WordStamp], lexicon: list[str]) -> list[Atom]:
    times = _char_times(text, stamps)
    words = _sorted_lexicon(lexicon)
    atoms: list[Atom] = []
    index = 0
    while index < len(text):
        if text[index].isspace():
            index += 1
            continue
        matched = _lexicon_at(text, index, words)
        if matched:
            end = index + len(matched)
        elif _is_latin(text[index]):
            end = _consume_latin(text, index)
        elif text[index] in _PUNCT:
            if atoms:
                atoms[-1].text += text[index]
                atoms[-1].end_s = times[index][2]
                if text[index] in _SENTENCE_END:
                    atoms[-1].break_after = True
            index += 1
            continue
        else:
            end = index + 1
        piece = text[index:end]
        atoms.append(Atom(text=piece, start_s=times[index][1], end_s=times[end - 1][2]))
        index = end
        while index < len(text) and text[index] in _PUNCT:
            atoms[-1].text += text[index]
            atoms[-1].end_s = times[index][2]
            if text[index] in _SENTENCE_END:
                atoms[-1].break_after = True
            index += 1
    return atoms


def highlight_spans(line: str, terms: list[str]) -> list[tuple[int, int, str]]:
    """Return non-overlapping (start, end, text) spans inside one line."""

    found: list[tuple[int, int, str]] = []
    used = [False] * len(line)
    candidates = [term for term in terms if term and len(term) >= 2]
    for match in _NUMBER.finditer(line):
        candidates.append(match.group(0))
    for match in _PHONE.finditer(line):
        candidates.append(match.group(0))
    ordered = sorted(set(candidates), key=len, reverse=True)
    for term in ordered:
        start = 0
        while True:
            index = line.find(term, start)
            if index < 0:
                break
            end = index + len(term)
            if any(used[index:end]):
                start = index + 1
                continue
            for cursor in range(index, end):
                used[cursor] = True
            found.append((index, end, line[index:end]))
            start = end
    found.sort(key=lambda item: item[0])
    return found


def alignment_error_ms(audio_start: float, audio_end: float, start_s: float, end_s: float) -> float:
    return max(abs(audio_start - start_s), abs(audio_end - end_s)) * 1000


def within_alignment(error_ms: float) -> bool:
    return error_ms <= ALIGNMENT_MS + 1e-6


def stamp_bounds(line: str, stamps: list[WordStamp]) -> tuple[float, float] | None:
    """Contiguous N6 tokens that spell this line, ignoring spaces and punctuation."""

    wanted = [char for char in line if not char.isspace() and char not in _PUNCT]
    if not wanted:
        return None
    flat: list[tuple[str, WordStamp]] = []
    for stamp in stamps:
        for char in stamp.text:
            if char.isspace() or char in _PUNCT:
                continue
            flat.append((char, stamp))
    width = len(wanted)
    for index in range(0, len(flat) - width + 1):
        window = [char for char, _stamp in flat[index : index + width]]
        if window == wanted:
            start = flat[index][1].start_s
            end = flat[index + width - 1][1].end_s
            return start, end
    return None


def _pack(atoms: list[Atom], *, zh: bool, limit: int) -> list[list[Atom]]:
    lines: list[list[Atom]] = []
    current: list[Atom] = []
    for atom in atoms:
        if not current:
            current = [atom]
        elif _length(_join(current + [atom], zh=zh), zh=zh) > limit:
            lines.append(current)
            current = [atom]
        else:
            current.append(atom)
        if current and current[-1].break_after:
            lines.append(current)
            current = []
    if current:
        lines.append(current)
    return lines


def _join(atoms: list[Atom], *, zh: bool) -> str:
    if zh:
        return "".join(atom.text for atom in atoms)
    return " ".join(atom.text for atom in atoms)


def _length(text: str, *, zh: bool) -> int:
    if zh:
        return sum(1 for char in text if not char.isspace())
    return len(text)


def _char_times(text: str, stamps: list[WordStamp]) -> list[tuple[str, float, float]]:
    assigned: list[tuple[str, float, float] | None] = [None] * len(text)
    cursor = 0
    for stamp in stamps:
        token = stamp.text
        if not token:
            continue
        index = text.find(token, cursor)
        if index < 0:
            continue
        span = max(0.0, stamp.end_s - stamp.start_s)
        count = len(token)
        for offset, _char in enumerate(token):
            start = stamp.start_s + span * offset / count
            end = stamp.start_s + span * (offset + 1) / count
            assigned[index + offset] = (text[index + offset], start, end)
        cursor = index + count
    last_end = 0.0
    filled: list[tuple[str, float, float]] = []
    for index, char in enumerate(text):
        item = assigned[index]
        if item is None:
            filled.append((char, last_end, last_end))
        else:
            filled.append(item)
            last_end = item[2]
    return filled


def _sorted_lexicon(words: list[str]) -> list[str]:
    cleaned = [word.strip() for word in words if word and word.strip()]
    return sorted(set(cleaned), key=len, reverse=True)


def _lexicon_at(text: str, index: int, words: list[str]) -> str | None:
    for word in words:
        if len(word) >= 2 and text.startswith(word, index):
            return word
    return None


def _is_latin(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _consume_latin(text: str, index: int) -> int:
    cursor = index
    while cursor < len(text):
        char = text[cursor]
        if char.isascii() and char.isalnum():
            cursor += 1
            continue
        nxt = text[cursor + 1] if cursor + 1 < len(text) else ""
        if char in "-./" and nxt.isascii() and nxt.isalnum():
            cursor += 1
            continue
        break
    if cursor < len(text) and text[cursor] == " ":
        end = cursor + 1
        while end < len(text) and text[end].isascii() and text[end].isalpha():
            end += 1
        if text[cursor + 1 : end] in _UNITS:
            cursor = end
    return cursor
