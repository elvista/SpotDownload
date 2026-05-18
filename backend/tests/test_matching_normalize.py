"""Tests for ``services.matching.normalize``.

The fixture set here is hand-curated. Each table row is a real shape we
see in DJ libraries (founder's library spot-check + DJCity pool listings):
YouTube rips with `(Official Video)` noise, Beatport/Spotify exports with
load-bearing `(Extended Mix)` tags, feat. variants, multi-artist
collaborations, and the YouTube-rip "Artist - Title" pattern with the
artist column empty.

Asserts target the *fields the rest of the pipeline reads*: that the
version tag survives, that cosmetic noise is gone, and that the artist
list comes out ordered with the primary first.
"""

from __future__ import annotations

import pytest

from services.matching.normalize import (
    NormalizedTrack,
    normalize_track,
    search_query,
)


def _n(title: str, artist: str | None = None) -> NormalizedTrack:
    return normalize_track(title, artist)


# ----- Cosmetic noise stripping ----------------------------------------


@pytest.mark.parametrize(
    "raw_title",
    [
        "Strobe (Official Video)",
        "Strobe (Official Music Video)",
        "Strobe (Lyric Video)",
        "Strobe [Official Audio]",
        "Strobe (HD)",
        "Strobe (4K)",
        "Strobe (Visualizer)",
        "Strobe (1080p)",
    ],
)
def test_strips_cosmetic_parentheticals(raw_title: str):
    n = _n(raw_title, "Deadmau5")
    assert n.title_clean == "strobe"
    assert n.title_base == "strobe"
    assert n.version_tag is None
    assert n.artists == ["deadmau5"]


# ----- Version tag preservation (the load-bearing kind) ----------------


@pytest.mark.parametrize(
    "raw_title,want_tag",
    [
        ("Strobe (Extended Mix)", "extended mix"),
        ("Strobe (Extended Vocal Mix)", "extended mix"),
        ("Strobe (Radio Edit)", "radio edit"),
        ("Strobe (Club Mix)", "club mix"),
        ("Strobe (Dub)", "dub mix"),
        ("Strobe (Dub Mix)", "dub mix"),
        ("Strobe (VIP)", "vip mix"),
        ("Strobe (VIP Mix)", "vip mix"),
        ("Strobe (Acapella)", "acapella"),
        ("Strobe (A Cappella)", "acapella"),
        ("Strobe (Instrumental)", "instrumental"),
        ("Strobe (Acoustic)", "acoustic"),
        ("Strobe (Original Mix)", "original mix"),
    ],
)
def test_keeps_load_bearing_version_tags(raw_title: str, want_tag: str):
    n = _n(raw_title, "Deadmau5")
    assert n.version_tag == want_tag, f"{raw_title=} → {n.version_tag=}"
    assert n.title_base == "strobe"
    # The clean form re-attaches the tag so pool search ranks it right.
    assert n.title_clean == f"strobe ({want_tag})"


def test_artist_remix_tag_keeps_artist_name():
    # Two different remixes of the same song are *different recordings*.
    # If the artist name doesn't survive, the wrong remix will silently
    # match — exactly the failure mode the slice exists to prevent.
    n1 = _n("Strobe (Calvin Harris Remix)", "Deadmau5")
    n2 = _n("Strobe (Disclosure Remix)", "Deadmau5")
    assert n1.version_tag == "calvin harris remix"
    assert n2.version_tag == "disclosure remix"
    assert n1.version_tag != n2.version_tag


def test_artist_bootleg_and_flip_and_edit_variants():
    assert _n("Strobe (Skrillex Bootleg)").version_tag == "skrillex bootleg"
    assert _n("Strobe (Skrillex Flip)").version_tag == "skrillex flip"
    assert _n("Strobe (Pegboard Nerds Edit)").version_tag == "pegboard nerds edit"


def test_first_version_tag_wins_when_two_present():
    # If a filename carries both noise and a version tag in two
    # parentheticals, we only keep the version one.
    n = _n("Strobe (Official Video) (Extended Mix)", "Deadmau5")
    assert n.version_tag == "extended mix"
    assert "official" not in n.title_clean


def test_bare_remix_with_no_artist_still_kept():
    n = _n("Strobe (Remix)", "Deadmau5")
    assert n.version_tag == "remix"


# ----- feat. canonicalisation -----------------------------------------


@pytest.mark.parametrize(
    "raw_artist",
    [
        "Drake feat. Rihanna",
        "Drake ft. Rihanna",
        "Drake ft Rihanna",
        "Drake featuring Rihanna",
        "Drake FEAT Rihanna",
    ],
)
def test_feat_canonical_form_in_artist_field(raw_artist: str):
    n = _n("Take Care", raw_artist)
    assert n.artists == ["drake", "rihanna"]


def test_feat_in_title_pulled_into_artists_list():
    # YouTube rips often encode the feature in the title; we surface it
    # so artist scoring sees it.
    n = _n("Lean On (feat. MØ)", "Major Lazer & DJ Snake")
    assert "mø" in n.artists
    assert n.artists[0] == "major lazer"


# ----- Artist splitting -----------------------------------------------


@pytest.mark.parametrize(
    "raw_artist,want",
    [
        ("Drake & Rihanna", ["drake", "rihanna"]),
        ("Drake, Rihanna", ["drake", "rihanna"]),
        ("Diplo x Sleepy Tom", ["diplo", "sleepy tom"]),
        ("Diplo + Sleepy Tom", ["diplo", "sleepy tom"]),
        ("Pendulum vs. The Prototypes", ["pendulum", "the prototypes"]),
        ("Knife Party with Tom Morello", ["knife party", "tom morello"]),
    ],
)
def test_artist_splitters(raw_artist: str, want: list[str]):
    n = _n("Whatever", raw_artist)
    assert n.artists == want


def test_duplicate_artists_deduped_preserving_order():
    n = _n("Whatever (feat. Drake)", "Drake & Rihanna")
    # "drake" appears in both the field and the title; we only count it
    # once, and the first occurrence wins (so the primary artist still
    # leads the list).
    assert n.artists == ["drake", "rihanna"]


# ----- "Artist - Title" YouTube-rip pattern ---------------------------


def test_youtube_rip_style_title_with_no_artist_field():
    # The "Artist - Title" pattern only fires when the artist field is
    # empty. We don't want it to mangle real titles with hyphens.
    n = _n("Deadmau5 - Strobe (Official Video)", artist=None)
    assert n.artists == ["deadmau5"]
    assert n.title_base == "strobe"


def test_hyphen_in_real_title_is_preserved_when_artist_field_present():
    # Critical: the YouTube-rip split must NOT fire when the artist field
    # is already populated, or we'd lose half of "Once In A Lifetime - Live"
    # style titles.
    n = _n("Once In A Lifetime - Live", "Talking Heads")
    assert n.title_base == "once in a lifetime - live"
    assert n.artists == ["talking heads"]


# ----- Unicode + whitespace handling ----------------------------------


def test_nfkc_normalization_collapses_fullwidth_chars():
    # "Ｓｔｒｏｂｅ" is full-width Latin (used in some Asian streaming
    # exports). NFKC should fold it back to ASCII.
    n = _n("Ｓｔｒｏｂｅ", "Deadmau5")
    assert n.title_base == "strobe"


def test_collapses_runs_of_whitespace():
    n = _n("Strobe    (Official  Video)", "  Deadmau5  ")
    assert n.title_base == "strobe"
    assert n.artists == ["deadmau5"]


def test_empty_inputs_dont_explode():
    n = _n("", "")
    assert n.title_clean == ""
    assert n.title_base == ""
    assert n.version_tag is None
    assert n.artists == []


# ----- Output helper --------------------------------------------------


def test_search_query_combines_title_and_primary_artist():
    n = _n("Strobe (Extended Mix)", "Deadmau5")
    q = search_query(n)
    # Order matters less than presence; what we care about is that the
    # version tag and the primary artist both land in the query.
    assert "strobe" in q
    assert "extended mix" in q
    assert "deadmau5" in q


def test_search_query_omits_artist_when_none_known():
    n = _n("Strobe", artist=None)
    assert search_query(n) == "strobe"


# ----- Acceptance criterion smoke test --------------------------------
#
# The slice plan's Phase 1/2 acceptance bar is: for ≥95% of the 50-track
# golden set, the normalised query is in the top 5 DJCity results. We
# can't run pool search in unit tests, but we can sanity-check that the
# normalisation is *stable and deterministic* — running it twice yields
# the same output, which is the property the eval harness relies on.


def test_normalization_is_idempotent():
    inputs = [
        ("Strobe (Official Video) (Extended Mix)", "Deadmau5"),
        ("Lean On (feat. MØ) (Official Music Video)", "Major Lazer & DJ Snake"),
        ("Take Care (Radio Edit) [HD]", "Drake feat. Rihanna"),
    ]
    for title, artist in inputs:
        first = normalize_track(title, artist)
        again = normalize_track(first.title_clean, ", ".join(first.artists))
        # Title base + version tag survive a round trip — the property
        # the eval harness depends on when it re-normalises pool result
        # titles before scoring.
        assert again.title_base == first.title_base
        assert again.version_tag == first.version_tag
