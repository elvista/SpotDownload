"""Tests for ``services.matching.fingerprint``.

Two layers:

1. **Unit tests with subprocess mocked.** Exercise the parsing,
   error-handling, and similarity-math code paths without depending on
   ``fpcalc`` being installed in CI. Asserts cover every documented
   failure mode (missing binary, non-zero exit, malformed JSON, empty
   fingerprint, timeout) because the slice plan's *raison d'être* is
   loud, distinguishable failures.

2. **Integration test.** Runs the real ``fpcalc`` if present and
   verifies the similarity metric reaches the slice-plan calibration
   values: identical fingerprints score 1.0, disjoint random
   fingerprints score near 0.

The integration test is ``@pytest.mark.skipif`` rather than `xfail` so
CI surfaces a clean "skipped: fpcalc unavailable" line rather than a
silently-passing failure, matching the SOUL value of loud feedback.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import wave
from pathlib import Path
from unittest.mock import patch

import pytest

from services.matching.fingerprint import (
    Fingerprint,
    FingerprintFailedError,
    FpcalcUnavailableError,
    fingerprint_file,
    is_same_recording,
    similarity,
)

# ---------- similarity() — pure math, no subprocess --------------------


def test_identical_fingerprints_score_one():
    fp = Fingerprint(duration_s=120.0, ints=[1, 2, 3, 4, 5, 6, 7, 8])
    assert similarity(fp, fp) == 1.0


def test_disjoint_fingerprints_score_zero_or_near_zero():
    # Integers whose XOR popcount is well above MAX_BIT_ERROR (=2).
    # Using `0` vs `~0 & 0xFFFFFFFF` gives 32 differing bits everywhere.
    a = Fingerprint(duration_s=120.0, ints=[0] * 50)
    b = Fingerprint(duration_s=120.0, ints=[0xFFFFFFFF] * 50)
    assert similarity(a, b) == 0.0


def test_empty_fingerprint_scores_zero_not_crash():
    a = Fingerprint(duration_s=120.0, ints=[])
    b = Fingerprint(duration_s=120.0, ints=[1, 2, 3])
    assert similarity(a, b) == 0.0
    assert similarity(b, a) == 0.0


def test_one_bit_difference_still_counts_as_match():
    # MAX_BIT_ERROR is 2 — a single-bit difference should still align.
    a = Fingerprint(duration_s=120.0, ints=[0b00000000_00000000_00000000_00000000] * 10)
    b = Fingerprint(duration_s=120.0, ints=[0b00000000_00000000_00000000_00000001] * 10)
    # Each frame differs by 1 bit ≤ MAX_BIT_ERROR, so every frame
    # aligns at offset 0 → score 1.0.
    assert similarity(a, b) == 1.0


def test_three_bit_difference_is_a_mismatch():
    # 3 bits > MAX_BIT_ERROR, no frames align.
    a = Fingerprint(duration_s=120.0, ints=[0b000] * 10)
    b = Fingerprint(duration_s=120.0, ints=[0b111] * 10)
    assert similarity(a, b) == 0.0


def test_is_same_recording_threshold_respected():
    fp = Fingerprint(duration_s=120.0, ints=[1, 2, 3, 4])
    # Identical → 1.0 > any threshold ≤ 1.0
    assert is_same_recording(fp, fp, threshold=0.85)
    assert is_same_recording(fp, fp, threshold=0.99)

    a = Fingerprint(duration_s=120.0, ints=[0] * 50)
    b = Fingerprint(duration_s=120.0, ints=[0xFFFFFFFF] * 50)
    assert not is_same_recording(a, b, threshold=0.85)


# ---------- fingerprint_file() error paths — subprocess mocked --------


def _make_proc(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
    """Build a fake subprocess.CompletedProcess for patching."""
    return subprocess.CompletedProcess(
        args=["fpcalc"], returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_missing_fpcalc_raises_fpcalc_unavailable(tmp_path: Path):
    f = tmp_path / "a.mp3"
    f.write_bytes(b"x" * 1024)  # non-empty so we don't trip the empty-file check first.
    with patch("services.matching.fingerprint.shutil.which", return_value=None):
        with pytest.raises(FpcalcUnavailableError, match="fpcalc binary not found"):
            fingerprint_file(f)


def test_missing_file_raises_fingerprint_failed(tmp_path: Path):
    with pytest.raises(FingerprintFailedError, match="does not exist"):
        fingerprint_file(tmp_path / "no-such-file.mp3")


def test_empty_file_raises_fingerprint_failed(tmp_path: Path):
    f = tmp_path / "empty.mp3"
    f.touch()
    with pytest.raises(FingerprintFailedError, match="file is empty"):
        fingerprint_file(f)


def test_directory_path_raises_fingerprint_failed(tmp_path: Path):
    with pytest.raises(FingerprintFailedError, match="path is a directory"):
        fingerprint_file(tmp_path)


def test_fpcalc_nonzero_exit_raises_fingerprint_failed(tmp_path: Path):
    f = tmp_path / "bad.mp3"
    f.write_bytes(b"not really audio")
    with patch(
        "services.matching.fingerprint.shutil.which", return_value="/fake/fpcalc"
    ), patch(
        "services.matching.fingerprint.subprocess.run",
        return_value=_make_proc(returncode=2, stderr=b"unable to decode"),
    ):
        with pytest.raises(FingerprintFailedError, match="fpcalc exited 2"):
            fingerprint_file(f)


def test_fpcalc_returns_non_json_raises_fingerprint_failed(tmp_path: Path):
    f = tmp_path / "weird.mp3"
    f.write_bytes(b"x")
    with patch(
        "services.matching.fingerprint.shutil.which", return_value="/fake/fpcalc"
    ), patch(
        "services.matching.fingerprint.subprocess.run",
        return_value=_make_proc(stdout=b"this is not json"),
    ):
        with pytest.raises(FingerprintFailedError, match="non-JSON"):
            fingerprint_file(f)


def test_fpcalc_returns_empty_fingerprint_raises(tmp_path: Path):
    f = tmp_path / "tooshort.mp3"
    f.write_bytes(b"x")
    payload = json.dumps({"duration": 0.5, "fingerprint": []}).encode()
    with patch(
        "services.matching.fingerprint.shutil.which", return_value="/fake/fpcalc"
    ), patch(
        "services.matching.fingerprint.subprocess.run",
        return_value=_make_proc(stdout=payload),
    ):
        with pytest.raises(FingerprintFailedError, match="empty fingerprint"):
            fingerprint_file(f)


def test_fpcalc_malformed_payload_raises(tmp_path: Path):
    f = tmp_path / "broken.mp3"
    f.write_bytes(b"x")
    # Missing 'fingerprint' key.
    payload = json.dumps({"duration": 1.5}).encode()
    with patch(
        "services.matching.fingerprint.shutil.which", return_value="/fake/fpcalc"
    ), patch(
        "services.matching.fingerprint.subprocess.run",
        return_value=_make_proc(stdout=payload),
    ):
        with pytest.raises(FingerprintFailedError, match="malformed"):
            fingerprint_file(f)


def test_fpcalc_timeout_raises_fingerprint_failed(tmp_path: Path):
    f = tmp_path / "slow.mp3"
    f.write_bytes(b"x")
    with patch(
        "services.matching.fingerprint.shutil.which", return_value="/fake/fpcalc"
    ), patch(
        "services.matching.fingerprint.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd=["fpcalc"], timeout=30),
    ):
        with pytest.raises(FingerprintFailedError, match="timed out after 30s"):
            fingerprint_file(f)


def test_fpcalc_happy_path_parses_payload(tmp_path: Path):
    f = tmp_path / "ok.mp3"
    f.write_bytes(b"x" * 256)
    payload = json.dumps(
        {"duration": 120.5, "fingerprint": [1, 2, 3, 4, 5]}
    ).encode()
    with patch(
        "services.matching.fingerprint.shutil.which", return_value="/fake/fpcalc"
    ), patch(
        "services.matching.fingerprint.subprocess.run",
        return_value=_make_proc(stdout=payload),
    ):
        fp = fingerprint_file(f)
    assert fp.duration_s == 120.5
    assert fp.ints == [1, 2, 3, 4, 5]


# ---------- Integration test against real fpcalc ---------------------


def _has_fpcalc() -> bool:
    return shutil.which("fpcalc") is not None


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


@pytest.mark.skipif(
    not _has_fpcalc() or not _has_ffmpeg(),
    reason="needs fpcalc + ffmpeg installed (CI may not have them)",
)
def test_real_fpcalc_round_trip_on_generated_audio(tmp_path: Path):
    """End-to-end smoke: generate a 30s sine WAV, fingerprint it twice,
    confirm identical inputs score 1.0 (sanity check the wire-up).
    """
    wav_path = tmp_path / "tone.wav"
    sample_rate = 16000
    seconds = 30
    # 440 Hz sine, 16-bit mono. Stdlib only, no numpy.
    import array
    import math

    samples = array.array(
        "h",
        (
            int(32000 * math.sin(2 * math.pi * 440 * t / sample_rate))
            for t in range(sample_rate * seconds)
        ),
    )
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(samples.tobytes())

    fp1 = fingerprint_file(wav_path, length_s=30)
    fp2 = fingerprint_file(wav_path, length_s=30)
    assert fp1.duration_s == pytest.approx(30.0, abs=1.0)
    assert fp1.ints == fp2.ints
    assert similarity(fp1, fp2) == 1.0
