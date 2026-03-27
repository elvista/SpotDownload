"""Mixtape ID scan loop: sample audio, fingerprint, dedupe, validate, SSE events."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from services import audio_processor
from services.audio_processor import cleanup_temp_file
from services.fingerprinter import fingerprinter

logger = logging.getLogger("spotdownload.mixtape_processor")

SAMPLE_INTERVAL = 15
# ACRCloud recommends short clips (~15s) per request for reliable ID (we use MP3 segments).
CHUNK_DURATION_SEC = 15
MIN_CONFIDENCE_THRESHOLD = 0.10
SAMPLE_TIMEOUT_MS = 60000

T = TypeVar("T")


def _cpu_batch_size() -> int:
    import os as _os

    try:
        n = len(_os.sched_getaffinity(0))
    except Exception:
        n = _os.cpu_count() or 4
    return max(2, min(6, max(2, n // 2)))


PARALLEL_BATCH_SIZE = _cpu_batch_size()


def format_timestamp(seconds: float) -> str:
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{mins}:{secs:02d}"


def normalize_track_info(artist: str, title: str) -> str:
    def norm(s: str) -> str:
        if not s:
            return ""
        s = s.lower()
        s = re.sub(r"\(.*?\)", "", s)
        s = re.sub(r"\[.*?\]", "", s)
        s = re.sub(r"feat\.|ft\.|featuring", "", s, flags=re.I)
        s = s.replace("&", "and")
        s = re.sub(r"\s+and\s+", ",", s)
        s = re.sub(r"[^a-z0-9,]", "", s)
        s = re.sub(r",+", ",", s)
        return s.strip()

    return f"{norm(artist)}|{norm(title)}"


def build_detection_context(
    detection: dict[str, Any], all_detections: list[dict[str, Any]], index: int
) -> dict[str, Any]:
    window = 300.0
    ctx: dict[str, Any] = {}
    nearby = [
        d
        for i, d in enumerate(all_detections)
        if i != index
        and abs(float(d.get("timestamp", 0)) - float(detection.get("timestamp", 0))) <= window
    ]
    da = detection.get("artist") or ""
    if da and any(
        normalize_track_info(d.get("artist", ""), "") in normalize_track_info(da, "")
        or normalize_track_info(d.get("artist", ""), "").startswith(
            normalize_track_info(da, "").split("|")[0]
        )
        for d in nearby
        if d.get("artist")
    ):
        ctx["nearbyArtistMatch"] = True
    if detection.get("album") and any(d.get("album") == detection.get("album") for d in nearby):
        ctx["albumContinuity"] = True
    g = detection.get("genre")
    if g:
        gs = [x.get("genre") for x in nearby if x.get("genre")]
        if gs.count(g) >= 2:
            ctx["genreConsistency"] = True
    key = normalize_track_info(detection.get("artist", ""), detection.get("title", ""))
    reps = sum(
        1
        for d in all_detections
        if d is not detection
        and normalize_track_info(d.get("artist", ""), d.get("title", "")) == key
    )
    if reps >= 2:
        ctx["repetitionDetected"] = True
    dur = detection.get("duration")
    if dur is not None and float(dur) < 90:
        ctx["suspiciouslyShort"] = True
    ctx["genre"] = g
    return ctx


def smart_deduplication(
    detections: list[dict[str, Any]], total_duration: float
) -> list[dict[str, Any]]:
    if not detections:
        return []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for d in detections:
        if not d.get("artist") or not d.get("title"):
            continue
        k = normalize_track_info(d["artist"], d["title"])
        grouped.setdefault(k, []).append(d)

    tracks: list[dict[str, Any]] = []
    for instances in grouped.values():
        instances.sort(key=lambda x: float(x["timestamp"]))
        best = max(instances, key=lambda x: float(x.get("confidence") or 0.5))
        first_t = float(instances[0]["timestamp"])
        last_t = float(instances[-1]["timestamp"])
        spread = last_t - first_t
        est_dur = min(spread + 60, 600) if spread > 0 else 180.0
        tracks.append(
            {
                "artist": best["artist"],
                "title": best["title"],
                "service": best.get("service") or best.get("serviceName"),
                "spotifyLink": best.get("spotifyLink"),
                "album": best.get("album"),
                "genre": best.get("genre"),
                "startTime": first_t,
                "endTime": min(first_t + est_dur, total_duration),
                "duration": min(est_dur, total_duration - first_t),
                "confidence": best.get("confidence") or 0.5,
                "verified": best.get("verified"),
                "detections": len(instances),
                "consensus": best.get("consensus"),
                "services": best.get("services"),
                "detectionSpread": spread,
            }
        )
    sorted_tracks = sorted(tracks, key=lambda t: t["startTime"])
    out = []
    for i, tr in enumerate(sorted_tracks):
        ctx = build_detection_context({**tr, "timestamp": tr["startTime"]}, sorted_tracks, i)
        out.append(fingerprinter.adjust_confidence_by_context(tr, ctx))
    return out


def validate_tracks(tracks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for track in tracks:
        if (track.get("confidence") or 0) < MIN_CONFIDENCE_THRESHOLD:
            continue
        st = float(track["startTime"])
        en = float(track["endTime"])
        duration = en - st
        warnings = []
        if duration < 120:
            warnings.append("Suspiciously short track (<2 min)")
        elif duration > 600:
            warnings.append("Unusually long track (>10 min)")
        if (track.get("confidence") or 0) < 0.5:
            warnings.append("Low confidence - may be incorrect")
        if not track.get("verified") and (track.get("confidence") or 0) < 0.7:
            warnings.append("Unverified identification")
        result.append({**track, "duration": duration, "warnings": warnings or None})
    return result


async def process_sample(
    file_path: str,
    start_time: float,
    duration: float,
    send_update: Callable[[dict[str, Any]], Awaitable[None] | None],
    segment_info: dict[str, Any],
) -> dict[str, Any] | None:
    async def _inner() -> dict[str, Any] | None:
        await send_update(
            {
                "type": "step",
                "step": "segmenting",
                "timestamp": format_timestamp(start_time),
                "segment": segment_info["current"],
                "totalSegments": segment_info["total"],
                "pass": segment_info["pass"],
            }
        )
        chunk_path = await audio_processor.extract_chunk(file_path, start_time, duration)
        try:
            await send_update(
                {
                    "type": "step",
                    "step": "fingerprinting",
                    "timestamp": format_timestamp(start_time),
                    "segment": segment_info["current"],
                    "totalSegments": segment_info["total"],
                    "pass": segment_info["pass"],
                }
            )
            result = await fingerprinter.identify_with_confidence(chunk_path, timeout=15.0)
            if result:
                result = fingerprinter.calibrate_confidence(result)
                fingerprinter.record_identification_result(
                    result.get("service") or "ACRCloud",
                    (result.get("confidence") or 0) >= MIN_CONFIDENCE_THRESHOLD,
                    float(result.get("confidence") or 0),
                    {"strategy": "standard", "genre": result.get("genre")},
                )
            await send_update(
                {
                    "type": "step",
                    "step": "matching",
                    "timestamp": format_timestamp(start_time),
                    "segment": segment_info["current"],
                    "totalSegments": segment_info["total"],
                    "pass": segment_info["pass"],
                    "matched": bool(result),
                }
            )
            return result
        finally:
            cleanup_temp_file(chunk_path)

    try:
        return await asyncio.wait_for(_inner(), timeout=SAMPLE_TIMEOUT_MS / 1000)
    except Exception as e:
        logger.warning("Sample at %s: %s", start_time, e)
        await send_update(
            {
                "type": "sample-error",
                "pass": segment_info.get("pass", 1),
                "segment": segment_info["current"],
                "totalSegments": segment_info["total"],
                "timestamp": format_timestamp(start_time),
                "error": str(e),
            }
        )
        return None


async def process_audio_file_streaming(
    file_path: str,
    session_id: str,
    mixtape_name: str,
    send_event: Callable[[dict[str, Any]], Awaitable[None]],
) -> bool:
    """Return True if scanning completed without fatal error."""

    async def send_update(data: dict[str, Any]) -> None:
        await send_event(data)

    try:
        fp_status = fingerprinter.fingerprint_env_status()
        if not fp_status.get("canIdentify"):
            msg = (
                "Fingerprinting APIs are not configured. Add ACRCloud (ACRCLOUD_HOST, "
                "ACRCLOUD_ACCESS_KEY, ACRCLOUD_ACCESS_SECRET) and/or AUDD_API_TOKEN to the "
                "repo-root .env, then restart the server. See GET /api/mixtape/fingerprint-status."
            )
            await send_update({"type": "error", "error": msg, "fingerprintStatus": fp_status})
            return False

        duration = await audio_processor.get_audio_duration(file_path)
        detections: list[dict[str, Any]] = []
        sent_songs: set[str] = set()
        total_samples_processed = 0
        formatted_duration = format_timestamp(duration)
        await send_update(
            {
                "type": "init",
                "duration": duration,
                "formattedDuration": formatted_duration,
                "pass": 1,
                "mixtapeName": mixtape_name,
            }
        )
        await send_update(
            {
                "type": "pass",
                "pass": 1,
                "description": f"Every {SAMPLE_INTERVAL}s, {CHUNK_DURATION_SEC}s clips → ACRCloud / AudD",
            }
        )

        scan_samples = []
        t = 0.0
        while t < duration:
            scan_samples.append({"time": t, "duration": float(CHUNK_DURATION_SEC)})
            t += SAMPLE_INTERVAL
        samples_completed = 0

        for i in range(0, len(scan_samples), PARALLEL_BATCH_SIZE):
            batch = scan_samples[i : i + PARALLEL_BATCH_SIZE]

            async def run_one(sample: dict[str, Any], batch_idx: int) -> dict[str, Any] | None:
                seg = {
                    "current": i + batch_idx + 1,
                    "total": len(scan_samples),
                    "pass": 1,
                }
                return await process_sample(
                    file_path,
                    float(sample["time"]),
                    float(sample["duration"]),
                    send_update,
                    seg,
                )

            tasks = [run_one(s, j) for j, s in enumerate(batch)]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for batch_idx, result in enumerate(results):
                total_samples_processed += 1
                sample = batch[batch_idx]
                samples_completed += 1
                await send_update(
                    {
                        "type": "progress",
                        "pass": 1,
                        "current": samples_completed,
                        "total": len(scan_samples),
                        "status": "done",
                        "timestamp": format_timestamp(sample["time"]),
                        "audioDuration": formatted_duration,
                    }
                )
                if isinstance(result, BaseException) or result is None:
                    continue
                conf = float(result.get("confidence") or 0)
                if conf < MIN_CONFIDENCE_THRESHOLD:
                    continue
                det = {**result, "timestamp": float(sample["time"]), "verified": False}
                detections.append(det)
                sk = normalize_track_info(result.get("artist", ""), result.get("title", ""))
                if sk not in sent_songs:
                    sent_songs.add(sk)
                    await send_update(
                        {
                            "type": "song",
                            "song": {**result, "timestamp": format_timestamp(sample["time"])},
                        }
                    )

        validated = smart_deduplication(detections, duration)
        final_tracks = validate_tracks(validated)
        stats = fingerprinter.get_cache_stats()

        # Send final-track before complete so clients still have an open SSE when they merge
        # the deduplicated list (closing on complete would drop these messages).
        for tr in final_tracks:
            await send_update(
                {
                    "type": "final-track",
                    "track": {
                        **tr,
                        "timestamp": format_timestamp(tr["startTime"]),
                        "endTime": format_timestamp(tr["endTime"])
                        if tr.get("endTime") is not None
                        else None,
                    },
                }
            )
        await send_update(
            {
                "type": "complete",
                "totalSongs": len(final_tracks),
                "totalSamples": total_samples_processed,
                "passes": 1,
                "stats": {
                    "cacheHitRate": stats["hitRate"],
                    "totalDetections": len(detections),
                    "finalTracks": len(final_tracks),
                },
            }
        )
        fingerprinter.save_persistent_cache()
        await asyncio.sleep(0.1)
        audio_processor.cleanup_all_temp_files()
        return True
    except Exception as e:
        logger.exception("process_audio_file_streaming: %s", e)
        await send_update({"type": "error", "error": str(e)})
        return False
