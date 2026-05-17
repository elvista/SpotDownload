import React, { useCallback, useState } from 'react';
import { api } from '../../api/client';
import ABPlayer from './ABPlayer';
import ReplaceButton from './ReplaceButton';
import { SpinnerIcon, CheckIcon, ErrorIcon } from '../Icons';

function basename(path) {
  if (!path) return '';
  const ix = path.lastIndexOf('/');
  return ix >= 0 ? path.slice(ix + 1) : path;
}

/**
 * Promoted view for a single pool hit chosen for preview. Wraps:
 *   - hit metadata (title, artist, pool, bitrate, format)
 *   - A/B audio preview (original vs pool hit) via ABPlayer
 *   - Confirm / Reject buttons → POST /upscale/match/:id/confirm | /reject
 *   - ReplaceButton, only enabled once the match is `confirmed`
 *
 * The card's local `status` tracks confirm/reject decisions so the UI is
 * responsive even before the next /search round-trip refreshes the hit list.
 */
export default React.memo(function MatchConfirmCard({ hit, candidate, onClose, onReplaced }) {
  const [status, setStatus] = useState('candidate');
  const [busy, setBusy] = useState(null); // 'confirm' | 'reject' | null
  const [error, setError] = useState(null);

  const handleConfirm = useCallback(async () => {
    setBusy('confirm');
    setError(null);
    try {
      const result = await api.upscale.confirmMatch(hit.upscale_match_id);
      setStatus(result.status || 'confirmed');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }, [hit.upscale_match_id]);

  const handleReject = useCallback(async () => {
    setBusy('reject');
    setError(null);
    try {
      const result = await api.upscale.rejectMatch(hit.upscale_match_id);
      setStatus(result.status || 'rejected');
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(null);
    }
  }, [hit.upscale_match_id]);

  const isConfirmed = status === 'confirmed';
  const isRejected = status === 'rejected';

  return (
    <section
      aria-labelledby={`match-confirm-${hit.upscale_match_id}`}
      className="rounded-xl border border-white/10 bg-spotify-dark-gray/80 p-4 space-y-3"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-[10px] uppercase tracking-wider text-spotify-light-gray/70">
            Preview match
          </p>
          <h3
            id={`match-confirm-${hit.upscale_match_id}`}
            className="text-base font-semibold text-white truncate"
            title={hit.title}
          >
            {hit.title || <em className="italic text-spotify-light-gray">Untitled</em>}
          </h3>
          <p className="text-sm text-spotify-light-gray truncate">
            {hit.artist || '—'}
          </p>
          <div className="flex items-center gap-2 mt-1 text-[10px] uppercase tracking-wider text-spotify-light-gray/80">
            <span className="px-1.5 py-0.5 rounded bg-spotify-green/15 text-spotify-green font-semibold">
              {hit.bitrate_kbps} kbps
            </span>
            <span>{hit.format}</span>
            {hit.duration_s ? <span>{Math.round(hit.duration_s)}s</span> : null}
            <span>· {hit.pool_slug}</span>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-xs text-spotify-light-gray hover:text-white px-2 py-1 rounded-md hover:bg-white/5 transition-colors shrink-0"
          aria-label="Close preview"
        >
          Close
        </button>
      </header>

      <ABPlayer
        originalUrl={api.upscale.previewOriginalUrl(hit.upscale_match_id)}
        newUrl={api.upscale.previewUrl(hit.upscale_match_id)}
        originalLabel="Current"
        originalSublabel={basename(candidate?.abs_path) || ''}
        newLabel="Pool hit"
        newSublabel={`${hit.pool_slug} · ${hit.bitrate_kbps} kbps`}
      />

      {error && (
        <div className="flex items-start gap-2 p-2.5 bg-red-900/30 border border-red-500/30 rounded-lg" role="alert">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-xs text-red-300">{error}</p>
        </div>
      )}

      <div className="flex items-center justify-between gap-2 flex-wrap pt-1">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleConfirm}
            disabled={busy !== null || isConfirmed || isRejected}
            aria-pressed={isConfirmed}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 ${
              isConfirmed
                ? 'bg-spotify-green/20 text-spotify-green border border-spotify-green/30'
                : 'bg-spotify-mid-gray hover:bg-white/10 text-white'
            }`}
          >
            {busy === 'confirm' ? (
              <><SpinnerIcon className="w-3.5 h-3.5" /> Confirming…</>
            ) : isConfirmed ? (
              <><CheckIcon className="w-3.5 h-3.5" /> Confirmed</>
            ) : (
              'Confirm match'
            )}
          </button>
          <button
            type="button"
            onClick={handleReject}
            disabled={busy !== null || isConfirmed || isRejected}
            className="px-3 py-1.5 text-xs font-medium rounded-lg text-spotify-light-gray hover:text-white hover:bg-white/5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {busy === 'reject' ? 'Rejecting…' : isRejected ? 'Rejected' : 'Reject'}
          </button>
        </div>
        <div title={!isConfirmed ? 'Confirm the match first' : ''}>
          <ReplaceButton
            match={{ id: hit.upscale_match_id, status }}
            libraryFileBasename={basename(candidate?.abs_path)}
            disabled={!isConfirmed}
            onReplaced={onReplaced}
          />
        </div>
      </div>
    </section>
  );
});
