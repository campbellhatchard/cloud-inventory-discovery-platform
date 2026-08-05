from __future__ import annotations


def clean_username(value: str) -> str:
    """Trim surrounding whitespace while preserving the chosen capitalization."""
    return value.strip()


def normalize_username(value: str) -> str:
    """Return the case-insensitive identity key used for lookup and uniqueness."""
    return clean_username(value).casefold()
