"""Title / artist normalization for the Upscale matching pipeline.

The job here is *narrow*: take whatever the ID3 tags / filenames threw at
us and produce a clean canonical form that pool search engines can match
against. No LLM, no scoring — just deterministic regex work.

Two principles drive every choice in this file:

1. **Strip the cosmetic, preserve the load-bearing.** ``(Official Video)``
   is noise. ``(Extended Mix)`` is *not* — DJCity often carries 6 versions
   of the same title (Original / Extended / Radio Edit / Dub / Acapella /
   VIP) and quietly mismatching them is the "silently wrong swap" failure
   mode the strategy plan calls out. Anything that *could* be a version
   tag stays attached.

2. **Tag everything we keep.** When we keep a parenthetical we lift its
   contents into a structured ``version_tag`` field so the scorer (PR4)
   can compare like-for-like instead of doing string match across the
   whole title.

Public API: :func:`normalize_track` returns a :class:`NormalizedTrack` —
that's what the pool query builder, the scorer, and ``decide`` all
consume.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class NormalizedTrack:
    """Output of :func:`normalize_track`.

    Attributes are the fields the rest of the pipeline reads.

    - ``title_clean`` — title with cosmetic parentheticals stripped, NFKC
      normalized, lowercased, whitespace collapsed. **Does** contain
      version tags (so a pool search "house music (extended mix)" still
      surfaces the right edit at the top).
    - ``title_base`` — title with *all* parentheticals removed. Used as
      a fallback search when ``title_clean`` returns nothing, and as the
      input to title-similarity scoring (we score on the base + compare
      version tags separately so a "Radio Edit" missing on the candidate
      doesn't tank an otherwise good match).
    - ``version_tag`` — canonical form of the kept parenthetical
      (``extended mix``, ``radio edit``, ``vip mix``, ``dub mix``,
      ``acoustic``, ``acapella``, ``instrumental``, ``<artist> remix``).
      None if the title carried no version info.
    - ``artists`` — primary first, featured artists after, in the order
      they appeared. All lowercased + NFKC. Used by the artist scorer.
    """

    title_clean: str
    title_base: str
    version_tag: str | None
    artists: list[str] = field(default_factory=list)


# Cosmetic parentheticals — strip these wholesale. Order matters only for
# debugging clarity; the regex is built case-insensitive and we strip
# matches in a single pass. New entries go at the end so reviewers can see
# the diff cleanly.
_NOISE_PATTERNS: tuple[str, ...] = (
    r"official\s*(music\s*)?video",
    r"official\s*audio",
    r"official\s*lyric\s*video",
    r"lyric\s*video",
    r"lyrics?",
    r"music\s*video",
    r"audio",
    r"visualizer",
    r"hd|4k|1080p|720p",
    r"hq",
    r"explicit",
    r"clean",
    r"remastered",  # not load-bearing for pool match — DJCity rarely splits
    r"with\s*lyrics",
)

# Compile once. The outer group captures the bracket type so we can match
# both ``(…)`` and ``[…]``; inner alternation matches any noise phrase.
_NOISE_RE = re.compile(
    r"[\(\[]\s*(?:" + "|".join(_NOISE_PATTERNS) + r")\s*[\)\]]",
    re.IGNORECASE,
)

# Load-bearing version tags we *keep* and canonicalize. The match order is
# significant: ``extended vocal mix`` must lose to ``extended mix`` only
# when ``vocal`` is absent, so the most specific patterns come first.
# Each tuple is (regex, canonical_form). Patterns are anchored to a
# parenthesis-or-bracket boundary so we don't catch ``mix`` in the middle
# of a word.
_VERSION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\(\[]\s*(extended\s*(vocal\s*)?mix)\s*[\)\]]", re.IGNORECASE), "extended mix"),
    (re.compile(r"[\(\[]\s*(radio\s*edit)\s*[\)\]]", re.IGNORECASE), "radio edit"),
    (re.compile(r"[\(\[]\s*(club\s*mix)\s*[\)\]]", re.IGNORECASE), "club mix"),
    (re.compile(r"[\(\[]\s*(dub\s*mix|dub)\s*[\)\]]", re.IGNORECASE), "dub mix"),
    (re.compile(r"[\(\[]\s*(vip\s*mix|vip)\s*[\)\]]", re.IGNORECASE), "vip mix"),
    (re.compile(r"[\(\[]\s*(acapella|a\s*cappella)\s*[\)\]]", re.IGNORECASE), "acapella"),
    (re.compile(r"[\(\[]\s*(instrumental)\s*[\)\]]", re.IGNORECASE), "instrumental"),
    (re.compile(r"[\(\[]\s*(acoustic)\s*[\)\]]", re.IGNORECASE), "acoustic"),
    (re.compile(r"[\(\[]\s*(original\s*mix)\s*[\)\]]", re.IGNORECASE), "original mix"),
    # "<X> Remix" / "<X> Edit" — keep the artist name attached so the
    # version tag stays distinguishing (Calvin Harris Remix !=
    # Disclosure Remix).
    (
        re.compile(r"[\(\[]\s*([^()\[\]]{1,40}?\s+remix)\s*[\)\]]", re.IGNORECASE),
        None,  # canonical form is the captured group, normalized
    ),
    (
        re.compile(r"[\(\[]\s*([^()\[\]]{1,40}?\s+edit)\s*[\)\]]", re.IGNORECASE),
        None,
    ),
    (
        re.compile(r"[\(\[]\s*([^()\[\]]{1,40}?\s+bootleg)\s*[\)\]]", re.IGNORECASE),
        None,
    ),
    (
        re.compile(r"[\(\[]\s*([^()\[\]]{1,40}?\s+flip)\s*[\)\]]", re.IGNORECASE),
        None,
    ),
    # Bare "Remix" with no artist is rare but seen in pool listings.
    (re.compile(r"[\(\[]\s*(remix)\s*[\)\]]", re.IGNORECASE), "remix"),
)

# `feat.` / `ft.` / `featuring` → canonical `feat.` regardless of casing.
# Anchored on the *leading* word boundary only: `\b` after `feat\.?` would
# fail when the optional dot is present (`.` is non-word, the following
# space is non-word too — no boundary), so the regex backtracks to match
# `feat` alone and leaves the literal dot behind. Lookahead for whitespace
# or end-of-string instead — that catches `feat`, `feat.`, `ft`, `ft.`,
# `featuring` uniformly without the dot-orphan bug.
_FEAT_RE = re.compile(
    r"\b(?:featuring|feat\.?|ft\.?)(?=\s|$)",
    re.IGNORECASE,
)

# Used to split artist strings on `&`, `,`, `x`, `+`, `vs.`, `with`. The
# `\bx\b` form is intentional — bare `x` is a common DJ-name separator
# ("Diplo x Sleepy Tom") but we don't want to split "Galantis x Hook'd".
_ARTIST_SPLIT_RE = re.compile(
    r"\s*(?:,|&|\+|\bx(?=\s)|\bvs\.?(?=\s)|\bversus(?=\s)|\bwith(?=\s)|/|\\)\s*",
    re.IGNORECASE,
)


def _collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _nfkc_lower(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold().strip()


def _extract_version_tag(title: str) -> tuple[str | None, str]:
    """Pull the first load-bearing parenthetical out of ``title``.

    Returns ``(version_tag_canonical, title_with_tag_removed)``. If no
    version tag is found, the version is None and the title is unchanged.
    """

    for pattern, canonical in _VERSION_PATTERNS:
        m = pattern.search(title)
        if not m:
            continue
        # Use the explicit canonical form if provided; otherwise lift the
        # captured group as the canonical (used for "<artist> remix"
        # variants).
        tag = canonical if canonical is not None else _nfkc_lower(_collapse_ws(m.group(1)))
        new_title = pattern.sub(" ", title, count=1)
        return tag, new_title
    return None, title


def _strip_all_parentheticals(s: str) -> str:
    # Used for ``title_base`` — strip every (...) and [...] group. Greedy
    # but non-nested; nested brackets in real-world filenames are
    # vanishingly rare and would already have failed our normalisation.
    s = re.sub(r"\([^()]*\)", " ", s)
    s = re.sub(r"\[[^\[\]]*\]", " ", s)
    return _collapse_ws(s)


def _split_artists(artist_field: str) -> list[str]:
    """Split a raw ID3 ``TPE1`` value into ordered, normalized artist names.

    ``feat.`` / ``ft.`` is canonicalised first so the split regex catches
    the join cleanly. Empty fragments are dropped (we get them when the
    source string ends with a separator).
    """

    if not artist_field:
        return []
    # `feat.` is itself a separator — featured artists land in the
    # artists list and the primary stays first. One sub does both the
    # canonicalisation and the split-point work.
    canonical = _FEAT_RE.sub(",", artist_field)
    parts = _ARTIST_SPLIT_RE.split(canonical)
    out: list[str] = []
    seen: set[str] = set()
    for raw in parts:
        name = _nfkc_lower(_collapse_ws(raw))
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out


def _featured_artists_from_title(title: str) -> tuple[str, list[str]]:
    """Pull ``feat. X & Y`` blocks out of the title and return them as a list.

    Producers sometimes encode features in the title rather than in
    ``TPE1`` (especially on YouTube rips). We surface them so the artist
    scorer sees the full picture.
    """

    # Normalise the feat-marker to a sentinel we can search for cleanly.
    canonical = _FEAT_RE.sub("FEAT_TOKEN", title)
    # Capture from FEAT_TOKEN to the next bracket boundary, separator dash,
    # or end-of-string. ``)``/``]`` are *closing* brackets and end an
    # inline `(feat. X)` block — they belong in the lookahead set.
    m = re.search(
        r"FEAT_TOKEN\s+([^()\[\]]+?)(?=\s*[\(\[\)\]]|\s*[-–|]|$)",
        canonical,
    )
    if not m:
        return title, []
    featured = _split_artists(m.group(1))
    cleaned = (canonical[: m.start()] + canonical[m.end() :]).strip()
    # Strip any sentinel residue and the now-empty brackets that wrapped
    # the feat. block ("Lean On (feat. MØ)" → "Lean On ()" → "Lean On").
    cleaned = cleaned.replace("FEAT_TOKEN", "")
    cleaned = re.sub(r"[\(\[]\s*[\)\]]", " ", cleaned)
    cleaned = _collapse_ws(cleaned)
    return cleaned, featured


def normalize_track(
    title: str,
    artist: str | None = None,
) -> NormalizedTrack:
    """Normalize a raw title + artist string into a ``NormalizedTrack``.

    ``title`` is the raw ID3 ``TIT2`` or filename. ``artist`` is the raw
    ``TPE1``; pass ``None`` if you only have the title (some YouTube rips
    embed the artist in the title with a `` - `` separator and we handle
    that here).
    """

    raw_title = title or ""
    raw_artist = artist or ""

    # Some YouTube rips look like "Artist - Title (Official Video)". If
    # we got an empty artist field, try to split on the first " - " before
    # we touch parentheticals.
    if not raw_artist and " - " in raw_title:
        head, _, tail = raw_title.partition(" - ")
        raw_artist = head
        raw_title = tail

    # 1. Strip cosmetic parentheticals.
    cleaned = _NOISE_RE.sub(" ", raw_title)

    # 2. Lift out the first load-bearing version tag (if any).
    version_tag, cleaned = _extract_version_tag(cleaned)

    # 3. Pull ``feat. X`` out of the title body into the featured list.
    cleaned, featured_in_title = _featured_artists_from_title(cleaned)

    # 4. NFKC + casefold + whitespace collapse on whatever remains.
    title_clean_body = _nfkc_lower(_collapse_ws(cleaned))

    # 5. The fully stripped base (used as a fallback query / scorer input).
    title_base = _nfkc_lower(_strip_all_parentheticals(title_clean_body))

    # 6. Re-attach the version tag to ``title_clean`` so pool search
    # surfaces the right edit. We deliberately do *not* attach it to
    # ``title_base``.
    title_clean = (
        f"{title_base} ({version_tag})" if version_tag else title_clean_body
    )

    # 7. Resolve artists.
    artists_from_field = _split_artists(raw_artist)
    artists: list[str] = []
    seen: set[str] = set()
    for name in [*artists_from_field, *featured_in_title]:
        if name in seen:
            continue
        seen.add(name)
        artists.append(name)

    return NormalizedTrack(
        title_clean=title_clean,
        title_base=title_base,
        version_tag=version_tag,
        artists=artists,
    )


def search_query(track: NormalizedTrack) -> str:
    """Build the string we pass to pool search engines.

    Pools rank reasonably well on ``"title artist"``; we just have to
    feed them a clean string. If we have a version tag we include it,
    because DJCity in particular indexes the version as part of the
    title.
    """

    parts = [track.title_clean]
    if track.artists:
        parts.append(track.artists[0])
    return _collapse_ws(" ".join(parts))
