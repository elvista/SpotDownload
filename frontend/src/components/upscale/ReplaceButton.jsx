import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { SpinnerIcon, CheckIcon, ErrorIcon } from '../Icons';
import BlockReasonsBanner from './BlockReasonsBanner';

const ARM_TIMEOUT_MS = 4000;

function basename(path) {
  if (!path) return '';
  const ix = path.lastIndexOf('/');
  return ix >= 0 ? path.slice(ix + 1) : path;
}

/**
 * Two-step Replace: first click arms ("Tap again to overwrite filename"),
 * second click within ARM_TIMEOUT_MS fires POST /upscale/match/:id/confirm
 * then POST /upscale/match/:id/replace.
 *
 * Surfaces three failure shapes distinctly:
 *  - 409 with detail.kind === 'fingerprint_block' → BlockReasonsBanner.
 *  - Other 409 (file locked, missing URL, not confirmed flow race) → plain red banner.
 *  - 5xx / network → generic red banner with err.message.
 */
export default React.memo(function ReplaceButton({ match, libraryFileBasename, onReplaced }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState(null);
  const [blockDetail, setBlockDetail] = useState(null);
  const armTimerRef = useRef(null);

  useEffect(() => () => {
    if (armTimerRef.current) clearTimeout(armTimerRef.current);
  }, []);

  const arm = useCallback(() => {
    setArmed(true);
    setError(null);
    setBlockDetail(null);
    if (armTimerRef.current) clearTimeout(armTimerRef.current);
    armTimerRef.current = setTimeout(() => setArmed(false), ARM_TIMEOUT_MS);
  }, []);

  const fire = useCallback(async () => {
    if (armTimerRef.current) clearTimeout(armTimerRef.current);
    setArmed(false);
    setBusy(true);
    setError(null);
    setBlockDetail(null);
    try {
      // Backend requires the match to be in 'confirmed' status before /replace.
      // We collapse confirm + replace into one founder-facing action.
      if ((match.status || '') !== 'confirmed') {
        await api.upscale.confirmMatch(match.id);
      }
      const result = await api.upscale.replaceMatch(match.id);
      setSuccess(true);
      if (onReplaced) onReplaced(result);
    } catch (err) {
      if (err.status === 409 && err.detail && typeof err.detail === 'object' && err.detail.kind === 'fingerprint_block') {
        setBlockDetail(err.detail);
      } else {
        setError(err.message || 'Replace failed');
      }
    } finally {
      setBusy(false);
    }
  }, [match, onReplaced]);

  const handleClick = useCallback(() => {
    if (busy || success) return;
    if (armed) {
      fire();
    } else {
      arm();
    }
  }, [armed, busy, success, arm, fire]);

  const fname = libraryFileBasename || basename(match?.library_file_path) || 'this file';

  if (success) {
    return (
      <div className="flex items-center gap-2 px-3 py-1.5 text-xs bg-spotify-green/15 border border-spotify-green/30 text-spotify-green rounded-lg" role="status">
        <CheckIcon className="w-3.5 h-3.5" />
        Replaced
      </div>
    );
  }

  return (
    <div className="space-y-2 w-full">
      <div className="flex items-center gap-2 flex-wrap">
        <button
          type="button"
          onClick={handleClick}
          disabled={busy}
          aria-pressed={armed}
          className={`px-3 py-1.5 text-xs font-semibold rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5 ${
            armed
              ? 'bg-red-500 hover:bg-red-600 text-white'
              : 'bg-spotify-green hover:bg-spotify-green-dark text-black'
          }`}
        >
          {busy ? (
            <><SpinnerIcon className="w-3.5 h-3.5" /> Replacing…</>
          ) : armed ? (
            'Tap again to overwrite'
          ) : (
            'Replace'
          )}
        </button>
        {armed && (
          <span className="text-xs text-spotify-light-gray min-w-0 truncate" title={fname}>
            Overwrites <span className="font-mono text-white">{fname}</span>
          </span>
        )}
      </div>

      {blockDetail && (
        <BlockReasonsBanner
          detail={blockDetail}
          onFindDifferent={() => setBlockDetail(null)}
        />
      )}

      {error && (
        <div className="flex items-start gap-2 p-2.5 bg-red-900/30 border border-red-500/30 rounded-lg" role="alert">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-xs text-red-300">{error}</p>
        </div>
      )}
    </div>
  );
});
