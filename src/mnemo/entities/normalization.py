"""Pure normalization for deterministic entity-name comparison."""

import unicodedata


def normalize_entity_name(value: str) -> str:
    """Normalize a name without erasing identity-significant distinctions.

    NFKC normalization is followed by outer trimming, whitespace collapsing,
    and Unicode case folding. Punctuation and diacritics remain intact.
    """
    normalized = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
    if not normalized:
        raise ValueError("entity name must not be blank")
    return normalized
