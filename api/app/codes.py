"""Beta / discount access codes: generation, normalisation, hashing.

Codes are random (never sequential) and persisted ONLY as a salted hash, so a
leak of the codes store reveals neither the plaintext codes nor the order they
were issued. The admin sees each plaintext code exactly once, at generation.

Hashing reuses the server pepper (Secret Manager), so the stored hash is useless
without the secret even if the database is exfiltrated.
"""
from __future__ import annotations

import hashlib
import secrets

from .config import get_settings

# Unambiguous alphabet: no 0/O/1/I/L so shared codes are easy to type/read.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_plaintext(prefix: str = "NK", groups: int = 3, size: int = 4) -> str:
    body = "-".join("".join(secrets.choice(_ALPHABET) for _ in range(size)) for _ in range(groups))
    return f"{prefix}-{body}"


def normalize(code: str) -> str:
    """Canonical form for hashing: uppercase, alphanumerics only (dashes/spaces ignored)."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def hash_code(code: str) -> str:
    pepper = get_settings().api_key_pepper or ""
    return hashlib.sha256((pepper + "|code|" + normalize(code)).encode("utf-8")).hexdigest()
