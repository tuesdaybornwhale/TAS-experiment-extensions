"""Tests for the Appendix-A rating scale helpers (providers/base.py)."""

from persona_preferences.providers.base import (
    RATING_SCALE_WORDS,
    RATING_WORD_TO_INT,
    map_word_ratings,
    opaque_label,
    rating_word_to_int,
)


def test_scale_words_and_encoding():
    assert RATING_SCALE_WORDS == [
        "strongly negative",
        "somewhat negative",
        "neutral",
        "somewhat positive",
        "strongly positive",
    ]
    assert [RATING_WORD_TO_INT[w] for w in RATING_SCALE_WORDS] == [1, 2, 3, 4, 5]
    assert RATING_WORD_TO_INT["neutral"] == 3


def test_rating_word_to_int_tolerant_forms():
    assert rating_word_to_int("strongly positive") == 5
    assert rating_word_to_int("Strongly_Positive") == 5
    assert rating_word_to_int("  NEUTRAL ") == 3
    assert rating_word_to_int("somewhat_negative") == 2


def test_rating_word_to_int_rejects_unknown():
    assert rating_word_to_int("negative") is None  # off-scale word (seen live from GPT-4o)
    assert rating_word_to_int("") is None
    assert rating_word_to_int(None) is None


def test_map_word_ratings_valid():
    assert map_word_ratings(["neutral", "strongly positive"], 2) == [3, 5]
    assert map_word_ratings(list(RATING_SCALE_WORDS), 5) == [1, 2, 3, 4, 5]


def test_map_word_ratings_invalid():
    assert map_word_ratings(["neutral"], 2) is None  # wrong length
    assert map_word_ratings(["neutral", "bogus"], 2) is None  # unknown word
    assert map_word_ratings("neutral", 1) is None  # not a list
    assert map_word_ratings(None, 0) is None


def test_opaque_labels():
    assert opaque_label(0) == "Identity A"
    assert opaque_label(1) == "Identity B"
    assert opaque_label(6) == "Identity G"
