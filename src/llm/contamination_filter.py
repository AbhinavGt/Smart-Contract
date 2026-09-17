"""Checks for fabricated external references in model output."""

from __future__ import annotations

import re


_KNOWN_ERC_NUMBERS = {
    "20", "165", "721", "777", "1155", "1967", "2612", "2981", "4626", "4907",
}
_ERC_PATTERN = re.compile(r"\b(?:ERC|EIP)-?(\d+)\b", re.IGNORECASE)
_URL_PATTERN = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_LIBRARY_PATTERN = re.compile(r"\b([A-Z][a-zA-Z0-9]+)\s+library\b")


def has_fabricated_standard_reference(text: str) -> bool:
    """Return true when an unrecognized ERC/EIP number is mentioned."""
    return any(
        match.group(1) not in _KNOWN_ERC_NUMBERS
        for match in _ERC_PATTERN.finditer(text)
    )


def looks_contaminated(text: str, source_code: str = "") -> bool:
    """Detect URLs, fabricated standards, or absent named libraries."""
    if _URL_PATTERN.search(text) or has_fabricated_standard_reference(text):
        return True
    if not source_code:
        return False
    return any(
        match.group(0).lower() not in source_code.lower()
        for match in _LIBRARY_PATTERN.finditer(text)
    )
