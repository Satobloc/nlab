#!/usr/bin/env python3
"""Detect standalone JSON conversation exports regardless of plaintext filename.

An nLab-local source scan must decide whether source is
structured JSON. This is a cheap, bounded *content sniff*, not a JSON parser
or an invitation to treat arbitrary prose containing braces as a conversation.

Any regular, non-symlinked file may qualify based on its contents, regardless
of extension. The probe reads at most 8192 bytes. Actual JSON decoding and
ChatGPT-conversation structure remain separate gates.
Original bytes, paths and file extensions are never rewritten here.
"""
from __future__ import annotations

from pathlib import Path

PLAINTEXT_JSON_SUFFIXES = frozenset({
    ".json", ".txt", ".text", ".md", ".markdown", ".log", ".raw", ".data",
    ".jsonl",
    "",  # extensionless plaintext JSON exports
})
_JSON_OPENERS = (b"{", b"[")
_MAX_PREFIX_BYTES = 8192


def is_json_document_candidate(path: Path) -> bool:
    """True when a permitted text document appears to contain standalone JSON.

    A .json filename remains eligible so malformed JSON is still recorded as
    a parse failure, consistent with the old date audit. All other names,
    whether .txt/.md or unusual extensions, must have an actual JSON opener
    following optional UTF-8 BOM/whitespace.
    Non-JSON prose, Markdown fenced code, and binary files are never promoted.
    """
    if path.is_symlink():
        return False
    try:
        if not path.is_file():
            return False
        if path.suffix.lower() == ".json":
            return True
        with path.open("rb") as stream:
            prefix = stream.read(_MAX_PREFIX_BYTES)
    except OSError:
        return False
    if prefix.startswith(b"\xef\xbb\xbf"):
        prefix = prefix[3:]
    return prefix.lstrip(b" \t\r\n").startswith(_JSON_OPENERS)
