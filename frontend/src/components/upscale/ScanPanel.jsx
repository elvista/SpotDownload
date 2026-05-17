import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { useUpscaleScanStream } from '../../hooks/useUpscaleScanStream';
import { SpinnerIcon, CheckIcon, ErrorIcon, RefreshIcon } from '../Icons';

function formatDuration(seconds) {
  if (seconds == null) return '';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  const remainderSec = Math.round(seconds % 60);
  return `${minutes}m ${remainderSec}s`;
}

function formatPath(p) {
  if (!p) return '';
  if (p.length <= 60) return p;
  return `…${p.slice(p.length - 60)}`;
}

export default React.memo(function ScanPanel({ onScanComplete, onOpenSettings }) {
  const [settings, setSettings] = useState({ library_root: '', threshold_kbps: 192 });
  const [settingsError, setSettingsError] = useState(null);
  const [startError, setStartError] = useState(null);
  const [scanId, setScanId] = useState(null);
  const [lastScan, setLastScan] = useState(null);

  const loadSettings = useCallback(async () => {
    try {
      const s = await api.upscale.getSettings();
      setSettings(s);
      setSettingsError(null);
    } catch (err) {
      setSettingsError(err.message);
    }
  }, []);

  const loadLastScan = useCallback(async () => {
    try {
      const runs = await api.upscale.listScans({ limit: 1 });
      setLastScan(runs && runs.length > 0 ? runs[0] : null);
    } catch {
      // Quiet: empty/missing scans aren't an error worth surfacing.
    }
  }, []);

  useEffect(() => {
    loadSettings();
    loadLastScan();
  }, [loadSettings, loadLastScan]);

  // Refresh the cached library root + threshold when the Settings modal saves
  // — otherwise the caption stays stale until the user navigates away and back.
  useEffect(() => {
    const onSaved = () => loadSettings();
    window.addEventListener('upscale:settings-saved', onSaved);
    return () => window.removeEventListener('upscale:settings-saved', onSaved);
  }, [loadSettings]);

  const stream = useUpscaleScanStream(scanId);
  const isScanning = stream.phase === 'scanning';

  // When a scan terminates, refresh last-scan summary + notify the parent.
  useEffect(() => {
    if (stream.phase === 'done') {
      loadLastScan();
      if (onScanComplete) onScanComplete({ scanId, candidates: stream.candidatesFound });
    }
  }, [stream.phase, stream.candidatesFound, scanId, loadLastScan, onScanComplete]);

  const handleStart = useCallback(async () => {
    setStartError(null);
    try {
      const result = await api.upscale.startScan();
      setScanId(result.scan_id);
    } catch (err) {
      setStartError(err.message);
    }
  }, []);

  const pct = stream.total > 0
    ? Math.min(100, Math.round((stream.scanned / stream.total) * 100))
    : 0;

  return (
    <section
      aria-labelledby="upscale-scan-heading"
      className="rounded-xl border border-white/5 bg-spotify-dark-gray/60 p-5 space-y-4"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="upscale-scan-heading" className="text-base font-semibold text-white">
            Library scan
          </h2>
          <p className="text-xs text-spotify-light-gray mt-0.5">
            Walks your music folder and flags files at or below{' '}
            <span className="text-white font-medium">{settings.threshold_kbps}</span> kbps as
            candidates for upscaling.
          </p>
        </div>
        {onOpenSettings && (
          <button
            type="button"
            onClick={onOpenSettings}
            className="text-xs text-spotify-light-gray hover:text-white px-2 py-1 rounded-md hover:bg-white/5 transition-colors shrink-0"
          >
            Settings
          </button>
        )}
      </header>

      <div className="text-xs text-spotify-light-gray space-y-1">
        <div>
          <span className="uppercase tracking-wider text-[10px] text-spotify-light-gray/70">
            Root
          </span>
          <p className="text-white font-mono mt-0.5 truncate" title={settings.library_root}>
            {settings.library_root || <em className="text-spotify-light-gray italic">Not set — open Settings</em>}
          </p>
        </div>
        {lastScan && lastScan.finished_at && (
          <p className="pt-1">
            Last scan: <span className="text-white">{lastScan.candidates}</span> candidates
            from <span className="text-white">{lastScan.files_seen}</span> files
            on{' '}
            <span className="text-white">
              {new Date(lastScan.finished_at).toLocaleString()}
            </span>.
          </p>
        )}
      </div>

      {/* Progress / status */}
      {isScanning ? (
        <div className="space-y-2" aria-live="polite">
          <div className="flex items-center justify-between text-xs">
            <span className="text-white">
              Scanned <span className="font-semibold">{stream.scanned}</span>
              {stream.total > 0 ? <> / {stream.total}</> : null}
              {' · '}
              <span className="text-spotify-green font-semibold">{stream.candidatesFound}</span>{' '}
              candidates
            </span>
            <span className="text-spotify-light-gray">{pct}%</span>
          </div>
          <div className="h-2 bg-spotify-mid-gray rounded-full overflow-hidden">
            <div
              className="h-full bg-spotify-green transition-[width] duration-200 ease-out"
              style={{ width: `${pct}%` }}
              role="progressbar"
              aria-valuenow={pct}
              aria-valuemin={0}
              aria-valuemax={100}
            />
          </div>
          {stream.current && (
            <p className="text-xs text-spotify-light-gray font-mono truncate" title={stream.current}>
              {formatPath(stream.current)}
            </p>
          )}
        </div>
      ) : stream.phase === 'done' ? (
        <div className="flex items-center gap-2 p-3 bg-spotify-green/10 border border-spotify-green/30 rounded-xl">
          <CheckIcon className="w-4 h-4 text-spotify-green shrink-0" />
          <p className="text-sm text-spotify-green">
            Found <span className="font-semibold">{stream.candidatesFound}</span> candidates
            from {stream.scanned} files in {formatDuration(stream.durationS)}.
          </p>
        </div>
      ) : stream.phase === 'error' ? (
        <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-500/30 rounded-xl">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{stream.error}</p>
        </div>
      ) : null}

      {settingsError && (
        <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-500/30 rounded-xl">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{settingsError}</p>
        </div>
      )}
      {startError && (
        <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-500/30 rounded-xl">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{startError}</p>
        </div>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleStart}
          disabled={isScanning || !settings.library_root}
          className="px-4 py-2 bg-spotify-green hover:bg-spotify-green-dark text-black font-semibold text-sm rounded-xl transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
        >
          {isScanning ? (
            <><SpinnerIcon className="w-4 h-4" /> Scanning…</>
          ) : stream.phase === 'done' || lastScan ? (
            <><RefreshIcon className="w-4 h-4" /> Rescan</>
          ) : (
            'Scan library'
          )}
        </button>
        {!settings.library_root && (
          <span className="text-xs text-spotify-light-gray">
            Set a library root in Settings first.
          </span>
        )}
      </div>
    </section>
  );
});
