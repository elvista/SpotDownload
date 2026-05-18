"""Chromaprint audio fingerprinting for the Upscale wrong-track guard.

The job of this module is *not* to identify a track — that's what the
pool scrapers + scorer do. The job is to answer a narrower question:
**"is the audio in file A perceptually the same recording as file B?"**

That distinction matters for the failure mode the AI slice exists to
prevent: the scorer can score a remix at 0.91 against the original
because the title + artist + duration line up, but the actual audio is
a different recording. Chromaprint sees the audio directly — different
recordings of the same song (remix vs original, live vs studio, cover
vs original) score below ~0.6 on the standard similarity metric, the
same recording at different bitrates scores >0.85.

## How it works

We shell out to ``fpcalc`` (Chromaprint's CLI, installed via
``brew install chromaprint`` on macOS or ``apt-get install
libchromaprint-tools`` on Linux). ``-raw -json`` gives us the integer
fingerprint array directly, bypassing the base64 encoding that
``pyacoustid.compare_fingerprints`` would otherwise need to decode.

The similarity computation is the same algorithm
``pyacoustid._match_fingerprints`` implements (sliding-window XOR with
``MAX_ALIGN_OFFSET=120``, ``MAX_BIT_ERROR=2``), reimplemented here so
this module doesn't pull in the python ``chromaprint`` C-extension
binding as a transitive requirement — ``fpcalc`` alone is enough.

## Loud, not silent

If ``fpcalc`` is missing or fails, we raise :class:`FpcalcUnavailableError`
or :class:`FingerprintFailedError` immediately. The caller (``decide``) maps
that to a ``block``-band decision so the founder sees "fingerprint
gate unavailable — install Chromaprint" rather than a swap going
through without the audio check. SOUL: *loud fallbacks surface bugs.*
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("cratedigger.upscale.matching.fingerprint")

# Bit-error tolerance per 32-bit Chromaprint frame: ≤2 differing bits ≈
# "this frame is the same recording, just lossy". Anything beyond is
# treated as a structural mismatch. Matches the upstream constants from
# pyacoustid so our scores are directly comparable with anything that
# came out of ``compare_fingerprints``.
_MAX_BIT_ERROR = 2
_MAX_ALIGN_OFFSET = 120

# Default sample window — long enough to be stable (Chromaprint's
# nominal minimum is 30s, recommended ≥120s) but short enough that
# fingerprinting a candidate doesn't dominate the swap latency budget
# (~2s wall clock at 120s on the founder's hardware).
_DEFAULT_LENGTH_S = 120


class FpcalcUnavailableError(RuntimeError):
    """Raised when the ``fpcalc`` binary is missing or unusable.

    The Upscale wrong-track guard is unsafe to silently skip, so
    callers turn this into a ``block``-band decision. See the README
    troubleshooting row "Upscale: fpcalc not found".
    """


class FingerprintFailedError(RuntimeError):
    """Raised when ``fpcalc`` ran but produced no usable fingerprint.

    Distinct from :class:`FpcalcUnavailableError` so the caller can
    tell "tooling missing" (operator problem) from "this file isn't
    parseable" (data problem) — e.g. zero-byte download, unsupported
    codec, truncated stream.
    """


@dataclass(frozen=True)
class Fingerprint:
    """Chromaprint fingerprint of one audio file.

    Attributes:
        duration_s: Audio duration reported by fpcalc (not necessarily
            the file's full duration — capped at the requested length).
        ints: Decoded integer fingerprint frames, used directly by
            :func:`similarity` without further parsing.
    """

    duration_s: float
    ints: list[int]


def _resolve_fpcalc() -> str:
    """Return the absolute path to fpcalc, or raise FpcalcUnavailableError.

    Resolved once per call rather than at import time so a backend
    that starts before the user has installed Chromaprint can still
    boot — the failure surfaces when the Upscale section actually
    needs the binary.
    """

    binary = shutil.which("fpcalc")
    if binary is None:
        raise FpcalcUnavailableError(
            "fpcalc binary not found on PATH. Install Chromaprint: "
            "`brew install chromaprint` (macOS) or "
            "`apt-get install libchromaprint-tools` (Linux). "
            "See README → Troubleshooting → 'Upscale: fpcalc not found'."
        )
    return binary


def fingerprint_file(path: Path | str, length_s: int = _DEFAULT_LENGTH_S) -> Fingerprint:
    """Compute the Chromaprint fingerprint of ``path``.

    ``length_s`` is the max audio duration fpcalc reads — 120s is the
    Chromaprint-recommended sample window. Shorter windows degrade
    similarity-score reliability; longer windows mostly add latency.
    """

    target = Path(path)
    if not target.exists():
        raise FingerprintFailedError(f"file does not exist: {target}")
    if target.is_dir():
        raise FingerprintFailedError(f"path is a directory, not a file: {target}")
    if target.stat().st_size == 0:
        raise FingerprintFailedError(f"file is empty: {target}")

    fpcalc = _resolve_fpcalc()
    cmd = [fpcalc, "-raw", "-json", "-length", str(int(length_s)), str(target)]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            timeout=max(30, int(length_s) + 30),
        )
    except subprocess.TimeoutExpired as e:
        raise FingerprintFailedError(
            f"fpcalc timed out after {e.timeout}s on {target.name}"
        ) from e

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise FingerprintFailedError(
            f"fpcalc exited {proc.returncode} on {target.name}: {stderr or '<no stderr>'}"
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise FingerprintFailedError(
            f"fpcalc returned non-JSON output on {target.name}: {e}"
        ) from e

    # fpcalc -raw -json shape: {"duration": <float>, "fingerprint": [int, int, …]}
    try:
        duration = float(payload["duration"])
        ints = [int(x) for x in payload["fingerprint"]]
    except (KeyError, TypeError, ValueError) as e:
        raise FingerprintFailedError(
            f"fpcalc payload malformed for {target.name}: {e}"
        ) from e

    if not ints:
        raise FingerprintFailedError(
            f"fpcalc produced empty fingerprint for {target.name} "
            f"(file too short? duration_reported={duration}s)"
        )
    return Fingerprint(duration_s=duration, ints=ints)


async def fingerprint_file_async(
    path: Path | str,
    length_s: int = _DEFAULT_LENGTH_S,
) -> Fingerprint:
    """Async wrapper for ``fingerprint_file``.

    fpcalc is CPU-bound so we offload to the default executor rather
    than blocking the event loop. The /upscale endpoints are async
    and a 2s sync call would stall every other request that hits the
    same worker.
    """

    return await asyncio.to_thread(fingerprint_file, path, length_s)


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    """Compare two fingerprints — score in [0, 1].

    Interpretation calibrated against the slice plan's gate values:
      - ≥ 0.85 → same recording (different bitrates of the same file).
      - 0.6 – 0.85 → close, but probably a different mix or master.
      - < 0.6 → different recording (remix, cover, live, wrong track).

    The algorithm is a sliding-window XOR alignment over the integer
    frames: for each frame ``i`` in ``a`` we scan ``±MAX_ALIGN_OFFSET``
    frames in ``b``, count frames that differ by at most
    ``MAX_BIT_ERROR`` bits, and take the best alignment offset. The
    score is the normalised count of matching frames at that offset
    over the shorter input. Identical inputs score 1.0 by definition.

    Complexity is O(N × ``MAX_ALIGN_OFFSET``); on a 120s
    fingerprint (~990 frames) that's well under 250ms on the founder's
    hardware — acceptable inside the swap-gate latency budget.
    """

    if not a.ints or not b.ints:
        return 0.0

    pa, pb = a.ints, b.ints
    asize, bsize = len(pa), len(pb)
    numcounts = asize + bsize + 1
    counts = [0] * numcounts

    for i in range(asize):
        jbegin = max(0, i - _MAX_ALIGN_OFFSET)
        jend = min(bsize, i + _MAX_ALIGN_OFFSET)
        for j in range(jbegin, jend):
            biterror = bin(pa[i] ^ pb[j]).count("1")
            if biterror <= _MAX_BIT_ERROR:
                offset = i - j + bsize
                counts[offset] += 1

    topcount = max(counts) if counts else 0
    denom = min(asize, bsize)
    if denom == 0:
        return 0.0
    return topcount / denom


def is_same_recording(a: Fingerprint, b: Fingerprint, threshold: float = 0.85) -> bool:
    """Convenience predicate for the ``decide`` gate.

    Threshold defaults to 0.85, the slice-plan cutoff for "same
    recording at different bitrates". The caller in ``decide`` passes
    its own threshold from app settings so we can re-tune without a
    code change.
    """

    return similarity(a, b) >= threshold
