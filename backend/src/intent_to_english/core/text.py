"""Deterministic text rules shared by model-output checks."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"[.!?…。\uff01\uff1f]+(?=\s|$)")
_ABBREVIATION = re.compile(r"\b(?:Mr|Mrs|Ms|Dr|St|vs|etc|e\.g|i\.e)$", re.IGNORECASE)
_LATIN = re.compile(
    r"[A-Za-z\uff21-\uff3a\uff41-\uff5a\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u017f]"
)
_JAPANESE = re.compile(
    r"[\u3041-\u309f\u30a0-\u30ff\u31f0-\u31ff\uff66-\uff9f"
    r"\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u3005]"
)


def split_sentences(text: str) -> tuple[str, ...]:
    """Split only at the sentence boundaries the conversation contract names."""
    sentences: list[str] = []
    start = 0
    for ending in _SENTENCE_END.finditer(text):
        if ending.group() == "." and _ABBREVIATION.search(text[: ending.start()]):
            continue
        if sentence := text[start : ending.end()].strip():
            sentences.append(sentence)
        start = ending.end()
    if trailing := text[start:].strip():
        sentences.append(trailing)
    return tuple(sentences)


def count_sentences(text: str) -> int:
    """Count a trailing fragment as a sentence too."""
    return len(split_sentences(text))


def count_questions(text: str) -> int:
    """Count both ASCII and fullwidth question marks."""
    return text.count("?") + text.count("\uff1f")


def has_latin_letter(text: str) -> bool:
    """Detect the Latin ranges forbidden in a build hint."""
    return _LATIN.search(text) is not None


def has_japanese_script(text: str) -> bool:
    """Detect Japanese scripts without treating punctuation as Japanese."""
    return _JAPANESE.search(text) is not None
