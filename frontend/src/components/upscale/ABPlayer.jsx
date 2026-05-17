import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useAudioCoordinator } from '../../hooks/useAudioCoordinator';

function formatTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${m}:${s}`;
}

function PlayerSide({ id, label, sublabel, src, accent, register, onPlay, onPause }) {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;
    return register(id, audio, () => setPlaying(false));
  }, [id, register]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;
    const onPlayE = () => { setPlaying(true); setError(null); if (onPlay) onPlay(); };
    const onPauseE = () => { setPlaying(false); if (onPause) onPause(); };
    const onTime = () => setCurrentTime(audio.currentTime || 0);
    const onLoaded = () => { setDuration(audio.duration || 0); setLoading(false); };
    const onLoadStart = () => setLoading(true);
    const onErr = () => {
      setError('Preview unavailable');
      setLoading(false);
      setPlaying(false);
    };
    audio.addEventListener('play', onPlayE);
    audio.addEventListener('pause', onPauseE);
    audio.addEventListener('timeupdate', onTime);
    audio.addEventListener('loadedmetadata', onLoaded);
    audio.addEventListener('loadstart', onLoadStart);
    audio.addEventListener('error', onErr);
    return () => {
      audio.removeEventListener('play', onPlayE);
      audio.removeEventListener('pause', onPauseE);
      audio.removeEventListener('timeupdate', onTime);
      audio.removeEventListener('loadedmetadata', onLoaded);
      audio.removeEventListener('loadstart', onLoadStart);
      audio.removeEventListener('error', onErr);
    };
  }, [onPause, onPlay]);

  const toggle = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) {
      audio.play().catch(() => setError('Playback blocked — try again'));
    } else {
      audio.pause();
    }
  }, []);

  const seek = useCallback((e) => {
    const audio = audioRef.current;
    if (!audio || !duration) return;
    audio.currentTime = Number(e.target.value);
    setCurrentTime(Number(e.target.value));
  }, [duration]);

  const accentClass = accent === 'green'
    ? 'border-spotify-green/30 bg-spotify-green/5'
    : 'border-white/10 bg-spotify-mid-gray/20';

  return (
    <div className={`rounded-lg border ${accentClass} p-3 flex flex-col gap-2`}>
      <div className="flex items-baseline justify-between gap-2 min-w-0">
        <p className="text-xs uppercase tracking-wider text-spotify-light-gray/80 shrink-0">
          {label}
        </p>
        <p className="text-xs text-spotify-light-gray truncate min-w-0" title={sublabel}>
          {sublabel}
        </p>
      </div>
      <audio ref={audioRef} src={src} preload="metadata" aria-label={`${label} preview`} />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={toggle}
          aria-label={playing ? `Pause ${label}` : `Play ${label}`}
          disabled={!!error}
          className={`w-9 h-9 shrink-0 rounded-full flex items-center justify-center transition-colors disabled:opacity-40 ${
            playing
              ? 'bg-white text-black'
              : 'bg-spotify-green text-black hover:bg-spotify-green-dark'
          }`}
        >
          {playing ? (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="5" width="4" height="14"/><rect x="14" y="5" width="4" height="14"/></svg>
          ) : (
            <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>
          )}
        </button>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={seek}
          disabled={!duration}
          aria-label={`${label} seek`}
          className="flex-1 accent-spotify-green"
        />
        <span className="text-[10px] text-spotify-light-gray font-mono w-16 text-right shrink-0">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>
      </div>
      {loading && !duration && (
        <p className="text-[10px] text-spotify-light-gray/70">Loading…</p>
      )}
      {error && (
        <p className="text-[10px] text-red-300">{error}</p>
      )}
    </div>
  );
}

/**
 * Side-by-side A/B audio preview: local file (left) vs pool hit (right).
 *
 * The `useAudioCoordinator` hook ensures starting playback on one side
 * pauses the other, preventing echo.
 */
export default React.memo(function ABPlayer({
  originalUrl,
  newUrl,
  originalLabel = 'Current',
  newLabel = 'Pool hit',
  originalSublabel = '',
  newSublabel = '',
}) {
  const { register } = useAudioCoordinator();
  return (
    <div
      role="region"
      aria-label="A/B audio preview"
      className="grid grid-cols-1 md:grid-cols-2 gap-3"
    >
      <PlayerSide
        id="original"
        label={originalLabel}
        sublabel={originalSublabel}
        src={originalUrl}
        accent="neutral"
        register={register}
      />
      <PlayerSide
        id="new"
        label={newLabel}
        sublabel={newSublabel}
        src={newUrl}
        accent="green"
        register={register}
      />
    </div>
  );
});
