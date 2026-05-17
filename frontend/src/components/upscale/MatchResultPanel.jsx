import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { SpinnerIcon, ErrorIcon } from '../Icons';
import MatchConfirmCard from './MatchConfirmCard';

function PoolHit({ hit, selected, onPreview }) {
  return (
    <li
      className={`rounded-lg border p-3 flex flex-col gap-1 transition-colors ${
        selected
          ? 'border-spotify-green/60 bg-spotify-green/10'
          : 'border-white/10 bg-spotify-mid-gray/30 hover:border-white/20'
      }`}
    >
      <p className="text-sm text-white font-medium truncate" title={hit.title}>
        {hit.title || <em className="text-spotify-light-gray italic">Untitled</em>}
      </p>
      <p className="text-xs text-spotify-light-gray truncate" title={hit.artist}>
        {hit.artist || '—'}
      </p>
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-spotify-light-gray/80 mt-1">
        <span className="px-1.5 py-0.5 rounded bg-spotify-green/20 text-spotify-green font-semibold">
          {hit.bitrate_kbps} kbps
        </span>
        <span>{hit.format}</span>
        {hit.duration_s ? <span>{Math.round(hit.duration_s)}s</span> : null}
      </div>
      <div className="flex justify-end pt-2">
        <button
          type="button"
          onClick={() => onPreview(hit)}
          aria-pressed={selected}
          className={`px-3 py-1 text-xs font-medium rounded-md transition-colors ${
            selected
              ? 'bg-spotify-green text-black hover:bg-spotify-green-dark'
              : 'bg-spotify-mid-gray text-white hover:bg-white/10'
          }`}
        >
          {selected ? 'Previewing' : 'Preview'}
        </button>
      </div>
    </li>
  );
}

function TriedRow({ row, servedBy, isFallback }) {
  const isServed = row.slug === servedBy;
  return (
    <li className="flex items-center justify-between text-xs px-3 py-1.5">
      <span
        className={`flex items-center gap-2 ${
          isServed ? 'text-spotify-green font-medium' : 'text-spotify-light-gray'
        }`}
      >
        <span
          className={`h-1.5 w-1.5 rounded-full ${
            isServed ? 'bg-spotify-green' : row.error ? 'bg-red-400' : 'bg-spotify-light-gray/50'
          }`}
          aria-hidden
        />
        {row.slug}
        {/* Fallback chevron: animates rightward when this pool returned 0 hits
            and the next-priority pool was tried after. */}
        {isFallback && (
          <svg
            className="w-3 h-3 text-amber-400 animate-pulse"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            aria-label="Falling back to next pool"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7l5 5m0 0l-5 5m5-5H6" />
          </svg>
        )}
      </span>
      <span className="text-spotify-light-gray">
        {row.error ? (
          <span className="text-red-300">{row.error}</span>
        ) : (
          <>{row.hits_count} hits</>
        )}
      </span>
    </li>
  );
}

export default React.memo(function MatchResultPanel({ candidate, onClose, onReplaced }) {
  const [state, setState] = useState({ loading: true, result: null, error: null });
  const [selectedHit, setSelectedHit] = useState(null);

  const search = useCallback(async () => {
    setState({ loading: true, result: null, error: null });
    setSelectedHit(null);
    try {
      const result = await api.upscale.search(candidate.id);
      setState({ loading: false, result, error: null });
    } catch (err) {
      setState({ loading: false, result: null, error: err.message });
    }
  }, [candidate.id]);

  useEffect(() => { search(); }, [search]);

  const { loading, result, error } = state;
  const hits = result?.hits || [];
  const tried = result?.tried || [];
  const servedBy = result?.served_by || '';

  // Each tried pool that contributed zero hits AND is followed by another pool
  // in the priority list triggered a fallback to the next one — render a
  // chevron animation pointing to the next row.
  const fallbackAt = new Set();
  for (let i = 0; i < tried.length - 1; i += 1) {
    if (tried[i].hits_count === 0) fallbackAt.add(tried[i].slug);
  }

  const handlePreview = useCallback((hit) => {
    setSelectedHit((prev) => (prev?.upscale_match_id === hit.upscale_match_id ? null : hit));
  }, []);

  const handleClosePreview = useCallback(() => setSelectedHit(null), []);

  return (
    <div
      className="rounded-xl border border-white/10 bg-spotify-dark-gray/80 p-4 space-y-3"
      role="region"
      aria-label={`Search results for ${candidate.tag_title || candidate.abs_path}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs uppercase tracking-wider text-spotify-light-gray/70">
            Searching pools for
          </p>
          <p className="text-sm text-white font-medium truncate" title={candidate.abs_path}>
            {candidate.tag_artist || candidate.tag_title
              ? `${candidate.tag_artist ? candidate.tag_artist + ' — ' : ''}${candidate.tag_title || ''}`
              : candidate.abs_path}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={search}
            disabled={loading}
            className="px-2 py-1 text-xs text-spotify-light-gray hover:text-white hover:bg-white/5 rounded-md transition-colors disabled:opacity-50"
          >
            {loading ? 'Searching…' : 'Retry'}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-2 py-1 text-xs text-spotify-light-gray hover:text-white hover:bg-white/5 rounded-md transition-colors"
            aria-label="Close search results"
          >
            Close
          </button>
        </div>
      </div>

      {tried.length > 0 && (
        <ul className="rounded-md bg-spotify-mid-gray/20 border border-white/5 divide-y divide-white/5">
          {tried.map((row) => (
            <TriedRow
              key={row.slug}
              row={row}
              servedBy={servedBy}
              isFallback={fallbackAt.has(row.slug)}
            />
          ))}
        </ul>
      )}

      {loading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-spotify-light-gray">
          <SpinnerIcon className="w-4 h-4" />
          <span>Querying DJ pools…</span>
        </div>
      ) : error ? (
        <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-500/30 rounded-xl">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{error}</p>
        </div>
      ) : hits.length === 0 ? (
        <p className="text-sm text-spotify-light-gray italic px-1 py-3">
          No hits across the configured pools.
          {servedBy ? '' : ' Pools may be disconnected — check Settings.'}
        </p>
      ) : (
        <>
          <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {hits.map((h) => (
              <PoolHit
                key={h.upscale_match_id}
                hit={h}
                selected={selectedHit?.upscale_match_id === h.upscale_match_id}
                onPreview={handlePreview}
              />
            ))}
          </ul>

          {selectedHit && (
            <MatchConfirmCard
              hit={selectedHit}
              candidate={candidate}
              onClose={handleClosePreview}
              onReplaced={(...args) => {
                handleClosePreview();
                if (onReplaced) onReplaced(...args);
              }}
            />
          )}
        </>
      )}
    </div>
  );
});
