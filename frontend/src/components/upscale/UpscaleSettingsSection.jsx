import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../../api/client';
import { SpinnerIcon, CheckIcon, ErrorIcon } from '../Icons';

const POOL_LOGIN_POLL_MS = 2500;

function formatRelative(iso) {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function PoolRow({ pool, busy, onConnect, onDisconnect }) {
  const { slug, displayName, connected, lastLogin, lastError, enabled } = pool;
  const statusDotClass = connected
    ? 'bg-spotify-green'
    : lastError
      ? 'bg-red-400'
      : 'bg-spotify-light-gray/50';
  return (
    <div className="flex items-center justify-between gap-3 py-2.5 border-b border-white/5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full shrink-0 ${statusDotClass}`}
            aria-hidden
          />
          <span className="text-sm font-medium text-white truncate">{displayName || slug}</span>
        </div>
        <p className="text-xs text-spotify-light-gray mt-0.5 truncate">
          {connected
            ? lastLogin ? `Connected · last login ${formatRelative(lastLogin)}` : 'Connected'
            : lastError
              ? lastError
              : enabled ? 'Not connected' : 'Pool scraping disabled in .env'}
        </p>
      </div>
      {connected ? (
        <button
          type="button"
          onClick={() => onDisconnect(slug)}
          disabled={busy}
          className="px-3 py-1.5 text-xs text-red-400 hover:text-red-300 hover:bg-red-900/20 rounded-lg transition-all disabled:opacity-50 whitespace-nowrap"
          aria-label={`Disconnect ${displayName || slug}`}
        >
          Disconnect
        </button>
      ) : (
        <button
          type="button"
          onClick={() => onConnect(slug)}
          disabled={busy || !enabled}
          className="px-3 py-1.5 text-xs font-medium bg-spotify-green hover:bg-spotify-green-dark text-black rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
          aria-label={`Connect ${displayName || slug}`}
          title={enabled ? '' : 'Set UPSCALE_POOLS_ENABLED=1 in .env to enable'}
        >
          {busy ? <SpinnerIcon className="w-3.5 h-3.5" /> : 'Connect'}
        </button>
      )}
    </div>
  );
}

export default React.memo(function UpscaleSettingsSection({ isOpen }) {
  const [libraryRoot, setLibraryRoot] = useState('');
  const [thresholdKbps, setThresholdKbps] = useState(192);
  const [pools, setPools] = useState([]);
  const [poolsFeatureFlagOff, setPoolsFeatureFlagOff] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);
  const [info, setInfo] = useState(null);
  const [poolBusy, setPoolBusy] = useState(null); // slug currently mid-login
  const pollTimerRef = useRef(null);
  const savedTimerRef = useRef(null);

  const normalizePool = useCallback((p) => ({
    slug: p.slug,
    displayName: p.display_name,
    connected: p.connected,
    lastLogin: p.last_login,
    lastError: p.last_error,
    enabled: p.enabled,
  }), []);

  const loadAll = useCallback(async () => {
    try {
      const settings = await api.upscale.getSettings();
      setLibraryRoot(settings.library_root || '');
      setThresholdKbps(settings.threshold_kbps || 192);
      setError(null);
    } catch (err) {
      setError(`Could not load Upscale settings: ${err.message}`);
    }
    try {
      const data = await api.upscale.getPools();
      const normalized = (data || []).map(normalizePool);
      setPools(normalized);
      setPoolsFeatureFlagOff(normalized.length > 0 && normalized.every((p) => !p.enabled));
    } catch (err) {
      if (err.status === 503) {
        setPoolsFeatureFlagOff(true);
        setPools([]);
      } else {
        setError(`Could not load DJ pools: ${err.message}`);
      }
    }
  }, [normalizePool]);

  useEffect(() => {
    if (isOpen) loadAll();
    return () => {
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current);
    };
  }, [isOpen, loadAll]);

  const handleSave = useCallback(async () => {
    if (!libraryRoot.trim()) {
      setError('Library root is required.');
      return;
    }
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await api.upscale.updateSettings({
        libraryRoot: libraryRoot.trim(),
        thresholdKbps: Number(thresholdKbps),
      });
      setLibraryRoot(updated.library_root);
      setThresholdKbps(updated.threshold_kbps);
      setSaved(true);
      // Let other Upscale surfaces (ScanPanel's "at or below X kbps" caption,
      // CandidateList's threshold readout) refresh without a full reload.
      window.dispatchEvent(new CustomEvent('upscale:settings-saved', { detail: updated }));
      savedTimerRef.current = setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }, [libraryRoot, thresholdKbps]);

  // Poll the pools endpoint after a login starts. Stop polling when the pool
  // either reports connected or surfaces a last_error.
  const pollPoolStatus = useCallback((slug) => {
    if (pollTimerRef.current) clearTimeout(pollTimerRef.current);
    const tick = async () => {
      try {
        const data = await api.upscale.getPools();
        const normalized = (data || []).map(normalizePool);
        setPools(normalized);
        const target = normalized.find((p) => p.slug === slug);
        if (target && (target.connected || target.lastError)) {
          setPoolBusy(null);
          if (target.connected) {
            setInfo(`${target.displayName} connected.`);
          } else if (target.lastError) {
            setError(`${target.displayName}: ${target.lastError}`);
          }
          return;
        }
      } catch {
        // Swallow transient poll errors and try again.
      }
      pollTimerRef.current = setTimeout(tick, POOL_LOGIN_POLL_MS);
    };
    pollTimerRef.current = setTimeout(tick, POOL_LOGIN_POLL_MS);
  }, [normalizePool]);

  const handleConnect = useCallback(async (slug) => {
    setError(null);
    setInfo(null);
    setPoolBusy(slug);
    try {
      await api.upscale.loginPool(slug);
      setInfo('A browser window opened on the backend host — complete login there. Status will update automatically.');
      pollPoolStatus(slug);
    } catch (err) {
      setPoolBusy(null);
      if (err.status === 503) {
        setPoolsFeatureFlagOff(true);
        setError('Pool scraping is disabled. Set UPSCALE_POOLS_ENABLED=1 in .env and restart the backend.');
      } else {
        setError(err.message);
      }
    }
  }, [pollPoolStatus]);

  const handleDisconnect = useCallback(async (slug) => {
    setError(null);
    setInfo(null);
    try {
      await api.upscale.clearPool(slug);
      await loadAll();
      setInfo(`${slug} session cleared.`);
    } catch (err) {
      setError(err.message);
    }
  }, [loadAll]);

  return (
    <div className="space-y-5 pt-2 border-t border-white/5">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-white">Upscale</h3>
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="px-3 py-1.5 text-xs bg-spotify-mid-gray hover:bg-white/10 text-white rounded-lg transition-all disabled:opacity-50 flex items-center gap-1.5"
        >
          {saving ? (<><SpinnerIcon className="w-3.5 h-3.5" /> Saving…</>)
            : saved ? (<><CheckIcon className="w-3.5 h-3.5" /> Saved</>)
            : 'Save Upscale'}
        </button>
      </div>

      <div>
        <label className="block text-sm font-medium text-white mb-2" htmlFor="upscale-library-root">
          Library root
        </label>
        <p className="text-xs text-spotify-light-gray mb-3">
          Folder scanned for low-bitrate tracks. Defaults to your download path.
        </p>
        <input
          id="upscale-library-root"
          type="text"
          value={libraryRoot}
          onChange={(e) => setLibraryRoot(e.target.value)}
          placeholder="/Users/you/Music/Library"
          className="w-full px-4 py-2.5 bg-spotify-mid-gray border border-white/10 rounded-xl text-white text-sm placeholder-gray-500 focus:outline-none focus:border-spotify-green focus:ring-1 focus:ring-spotify-green transition-all font-mono"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-white mb-2" htmlFor="upscale-threshold">
          Bitrate threshold
        </label>
        <p className="text-xs text-spotify-light-gray mb-3">
          Files at or below this kbps are flagged as candidates for upscaling.
        </p>
        <div className="flex items-center gap-3">
          <input
            id="upscale-threshold"
            type="number"
            min={32}
            max={2048}
            value={thresholdKbps}
            onChange={(e) => setThresholdKbps(Math.max(32, parseInt(e.target.value, 10) || 32))}
            className="w-24 px-4 py-2.5 bg-spotify-mid-gray border border-white/10 rounded-xl text-white text-sm focus:outline-none focus:border-spotify-green focus:ring-1 focus:ring-spotify-green transition-all"
          />
          <span className="text-sm text-spotify-light-gray">kbps</span>
        </div>
      </div>

      <div>
        <h4 className="text-sm font-medium text-white mb-1">DJ Pool Connections</h4>
        <p className="text-xs text-spotify-light-gray mb-3">
          Connect each pool once. Login opens a browser window on the backend
          host so you can complete Cloudflare / Captcha / 2FA by hand. Sessions
          are stored encrypted and survive restarts.
        </p>
        {poolsFeatureFlagOff && pools.length === 0 ? (
          <div className="p-3 bg-amber-900/30 border border-amber-500/30 rounded-xl">
            <p className="text-sm text-amber-200">
              Pool scraping is disabled. Set <code className="text-xs font-mono">UPSCALE_POOLS_ENABLED=1</code>{' '}
              in <code className="text-xs font-mono">.env</code> and restart the backend.
            </p>
          </div>
        ) : pools.length === 0 ? (
          <p className="text-xs text-spotify-light-gray italic">No pool scrapers registered yet.</p>
        ) : (
          <div className="rounded-xl bg-spotify-mid-gray/30 border border-white/10 px-3">
            {pools.map((p) => (
              <PoolRow
                key={p.slug}
                pool={p}
                busy={poolBusy === p.slug}
                onConnect={handleConnect}
                onDisconnect={handleDisconnect}
              />
            ))}
          </div>
        )}
      </div>

      {info && (
        <div className="p-3 bg-spotify-green/10 border border-spotify-green/30 rounded-xl">
          <p className="text-sm text-spotify-green">{info}</p>
        </div>
      )}
      {error && (
        <div className="p-3 bg-red-900/30 border border-red-500/30 rounded-xl flex items-start gap-2">
          <ErrorIcon className="w-4 h-4 mt-0.5 text-red-400 shrink-0" />
          <p className="text-sm text-red-300">{error}</p>
        </div>
      )}
    </div>
  );
});
