# SPDX-License-Identifier: MIT
# Copyright (c) 2026 IURII Potekhin
# Purpose: provide objective checks for the project English writing profile.
"""Objective checks for the project Simplified Technical English profile."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable, Sequence


DESCRIPTIVE_WORD_LIMIT = 25
PROCEDURAL_WORD_LIMIT = 20

DEFAULT_DOCUMENTS = (
    "AGENTS.md",
    "COPYRIGHT.md",
    "DISCLAIMER.md",
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "THIRD_PARTY_NOTICES.md",
    "TRADEMARKS.md",
    "docs/ARCHITECTURE.md",
    "docs/COMMAND_REFERENCE.md",
    "docs/CONFIGURATION.md",
    "docs/IMPLEMENTATION_STATUS.md",
    "docs/INTRODUCTION.md",
    "docs/LOCAL_ARTIFACTS.md",
    "docs/RASPBERRY_PI_INSTALL.md",
    "docs/RELEASING.md",
    "docs/RUNTIME_SAFETY_AND_REPORTING.md",
    "docs/TECHNICAL_ENGLISH.md",
)

_CONTRACTION_RE = re.compile(
    r"\b(?:can't|cannot've|couldn't|didn't|doesn't|don't|hadn't|hasn't|haven't|"
    r"isn't|mustn't|shouldn't|wasn't|weren't|won't|wouldn't|it's|that's|there's|"
    r"they're|we're|we've|you're|you've)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9'/-]*")
_SENTENCE_RE = re.compile(r"(?<=[.!?])(?:\s+|$)")
_LIST_RE = re.compile(r"^(?P<mark>(?:\d+[.)]|[-+*]))\s+(?P<body>.*)$")
_LINK_RE = re.compile(r"\[([^]]+)\]\([^)]+\)")
_CODE_RE = re.compile(r"`[^`]+`")
_HTML_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class TechnicalEnglishIssue:
    """One objective writing-profile violation."""

    path: Path
    line: int
    rule: str
    message: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}"


@dataclass(frozen=True)
class _Paragraph:
    line: int
    text: str
    procedural: bool


def _plain_text(value: str) -> str:
    value = _LINK_RE.sub(r"\1", value)
    value = _CODE_RE.sub("TERM", value)
    value = _HTML_RE.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip()


def _paragraphs(markdown: str) -> Iterable[_Paragraph]:
    """Yield prose paragraphs and skip code, tables, headings, and raw HTML."""

    in_code = False
    start = 0
    parts: list[str] = []
    procedural = False

    def flush() -> _Paragraph | None:
        nonlocal parts, start, procedural
        if not parts:
            return None
        result = _Paragraph(start, " ".join(parts), procedural)
        parts = []
        start = 0
        procedural = False
        return result

    for line_number, raw_line in enumerate(markdown.splitlines(), 1):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            paragraph = flush()
            if paragraph is not None:
                yield paragraph
            in_code = not in_code
            continue
        if in_code:
            continue

        list_match = _LIST_RE.match(stripped)
        excluded = (
            not stripped
            or stripped.startswith("#")
            or stripped.startswith("|")
            or stripped.startswith("<")
            or stripped.startswith("![")
            or stripped in {"---", "***", "___"}
        )
        if excluded or list_match is not None:
            paragraph = flush()
            if paragraph is not None:
                yield paragraph
            if list_match is not None:
                body = list_match.group("body")
                if body:
                    start = line_number
                    parts = [body]
                    procedural = list_match.group("mark")[0].isdigit()
            continue

        if not parts:
            start = line_number
        parts.append(stripped)

    paragraph = flush()
    if paragraph is not None:
        yield paragraph


def check_document(path: Path) -> list[TechnicalEnglishIssue]:
    """Check the objective subset of the project writing profile."""

    issues: list[TechnicalEnglishIssue] = []
    markdown = path.read_text(encoding="utf-8")
    for paragraph in _paragraphs(markdown):
        plain = _plain_text(paragraph.text)
        if not plain:
            continue
        contraction = _CONTRACTION_RE.search(plain)
        if contraction is not None:
            issues.append(
                TechnicalEnglishIssue(
                    path,
                    paragraph.line,
                    "STE-CONTRACTION",
                    f"replace the contraction {contraction.group(0)!r}",
                )
            )
        limit = PROCEDURAL_WORD_LIMIT if paragraph.procedural else DESCRIPTIVE_WORD_LIMIT
        for sentence in _SENTENCE_RE.split(plain):
            sentence = sentence.strip()
            if not sentence:
                continue
            count = len(_WORD_RE.findall(sentence))
            if count > limit:
                kind = "procedural" if paragraph.procedural else "descriptive"
                issues.append(
                    TechnicalEnglishIssue(
                        path,
                        paragraph.line,
                        "STE-SENTENCE-LENGTH",
                        f"{kind} sentence has {count} words; maximum is {limit}",
                    )
                )
    return issues


def check_documents(root: Path, documents: Sequence[str] = DEFAULT_DOCUMENTS) -> list[TechnicalEnglishIssue]:
    """Check each configured documentation file below *root*."""

    issues: list[TechnicalEnglishIssue] = []
    for name in documents:
        path = root / name
        if not path.is_file():
            issues.append(
                TechnicalEnglishIssue(path, 1, "STE-MISSING-DOCUMENT", "required document is missing")
            )
            continue
        issues.extend(check_document(path))
    return issues
