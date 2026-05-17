import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { SpinnerIcon, ErrorIcon } from '../Icons';

const DEFAULT_LIMIT = 25;

function basename(path) {
  if (!path) return '';
  const ix = path.lastIndexOf('/');
  return ix >= 0 ? path.slice(ix + 1) : path;
}

function formatTimestamp(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

function bytesShort(n) {
  if (!n) return '—';
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)}KB`;
  return `${(n / (1024 * 1024)).toFixed(1)}MB`;
}

function CopyButton({ text }) {
  const [copied, setCopied] = useState(false);
  const onClick = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API may be unavailable in non-secure contexts; ignore.
    }
  }, [text]);
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-spotify-light-gray hover:text-white text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded hover:bg-white/5 transition-colors"
      aria-label="Copy path to clipboard"
    >
      {copied ? 'Copied' : 'Copy'}
    </button>
  );
}

export default React.memo(function ReplaceLogTable({ refreshKey = 0, libraryFileId }) {
  const [page, setPage] = useState({ items: [], total: 0, offset: 0 });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async (nextOffset) => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.upscale.getReplaceLog({
        limit: DEFAULT_LIMIT,
        offset: nextOffset,
        libraryFileId,
      });
      setPage({
        items: result.items || [],
        total: result.total || 0,
        offset: result.offset || 0,
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [libraryFileId]);

  useEffect(() => { load(0); }, [load, refreshKey]);

  const handlePage = useCallback((delta) => {
    const next = Math.max(0, page.offset + delta * DEFAULT_LIMIT);
    if (next === page.offset) return;
    load(next);
  }, [load, page.offset]);

  const { items, total, offset } = page;
  const start = total === 0 ? 0 : offset + 1;
  const end = Math.min(offset + items.length, total);

  return (
    <section
      aria-labelledby="upscale-log-heading"
      className="rounded-xl border border-white/5 bg-spotify-dark-gray/60 p-5 space-y-3"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="upscale-log-heading" className="text-base font-semibold text-white">
            Replace Log
          </h2>
          <p className="text-xs text-spotify-light-gray mt-0.5">
            History of swaps. Originals are archived alongside the path shown.
          </p>
        </div>
        {!loading && total > 0 && (
          <p className="text-xs text-spotify-light-gray shrink-0 mt-1">
            <span className="text-white font-medium">{start}</span>–
            <span className="text-white font-medium">{end}</span> of{' '}
            <span className="text-white font-medium">{total}</span>
          </p>
        )}
      </header>

      {loading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-spotify-light-gray">
          <SpinnerIcon className="w-4 h-4" />
          <span>Loading replace log…</span>
        </div>
      ) : error ? (
        <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-500/30 rounded-xl">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{error}</p>
        </div>
      ) : items.length === 0 ? (
        <p className="px-1 py-4 text-sm text-spotify-light-gray italic">
          No swaps yet. Run a scan, search a candidate, and Replace to populate this log.
        </p>
      ) : (
        <>
          {/* Desktop table */}
          <div className="hidden md:block rounded-xl bg-spotify-mid-gray/20 border border-white/5 overflow-hidden">
            <table className="w-full text-xs">
              <thead className="bg-spotify-mid-gray/40 text-spotify-light-gray uppercase tracking-wider">
                <tr>
                  <th className="text-left px-3 py-2 font-medium">When</th>
                  <th className="text-left px-3 py-2 font-medium">File</th>
                  <th className="text-left px-3 py-2 font-medium">Pool</th>
                  <th className="text-right px-3 py-2 font-medium">Bitrate</th>
                  <th className="text-right px-3 py-2 font-medium">Size</th>
                  <th className="text-left px-3 py-2 font-medium">Archive</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {items.map((r) => (
                  <tr key={r.id} className="hover:bg-white/[0.02]">
                    <td className="px-3 py-2 text-spotify-light-gray whitespace-nowrap">
                      {formatTimestamp(r.replaced_at)}
                    </td>
                    <td className="px-3 py-2 text-white max-w-[12rem] truncate" title={r.abs_path}>
                      {basename(r.abs_path)}
                    </td>
                    <td className="px-3 py-2 text-spotify-light-gray">{r.pool_slug || '—'}</td>
                    <td className="px-3 py-2 text-right text-white font-mono whitespace-nowrap">
                      <span className="text-red-300">{r.old_bitrate_kbps}</span>
                      <span className="text-spotify-light-gray/60 mx-1">→</span>
                      <span className="text-spotify-green">{r.new_bitrate_kbps}</span>
                    </td>
                    <td className="px-3 py-2 text-right text-spotify-light-gray font-mono whitespace-nowrap">
                      {bytesShort(r.file_size_before)} → {bytesShort(r.file_size_after)}
                    </td>
                    <td className="px-3 py-2 text-spotify-light-gray flex items-center gap-2 min-w-0">
                      <span className="truncate max-w-[14rem] font-mono text-[10px]" title={r.archive_path}>
                        {basename(r.archive_path)}
                      </span>
                      <CopyButton text={r.archive_path} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile / tablet cards */}
          <ul className="md:hidden rounded-xl bg-spotify-mid-gray/20 border border-white/5 divide-y divide-white/5">
            {items.map((r) => (
              <li key={r.id} className="px-3 py-3 space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm text-white font-medium truncate" title={r.abs_path}>
                    {basename(r.abs_path)}
                  </span>
                  <span className="text-[10px] text-spotify-light-gray shrink-0">
                    {formatTimestamp(r.replaced_at)}
                  </span>
                </div>
                <div className="text-xs text-spotify-light-gray flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-mono">
                    <span className="text-red-300">{r.old_bitrate_kbps}</span>
                    <span className="mx-1">→</span>
                    <span className="text-spotify-green">{r.new_bitrate_kbps}</span>
                    {' kbps'}
                  </span>
                  <span>{r.pool_slug || '—'}</span>
                  <span className="font-mono">
                    {bytesShort(r.file_size_before)} → {bytesShort(r.file_size_after)}
                  </span>
                </div>
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[10px] text-spotify-light-gray/80 font-mono truncate" title={r.archive_path}>
                    {r.archive_path}
                  </span>
                  <CopyButton text={r.archive_path} />
                </div>
              </li>
            ))}
          </ul>

          {total > items.length && (
            <div className="flex items-center justify-between gap-3 pt-1">
              <button
                type="button"
                onClick={() => handlePage(-1)}
                disabled={offset === 0}
                className="px-3 py-1.5 text-xs bg-spotify-mid-gray hover:bg-white/10 text-white rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Previous
              </button>
              <button
                type="button"
                onClick={() => handlePage(1)}
                disabled={offset + items.length >= total}
                className="px-3 py-1.5 text-xs bg-spotify-mid-gray hover:bg-white/10 text-white rounded-md transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Next
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
});
