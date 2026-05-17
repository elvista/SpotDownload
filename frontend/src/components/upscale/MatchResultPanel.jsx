import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import { SpinnerIcon, ErrorIcon } from '../Icons';
import ReplaceButton from './ReplaceButton';

function PoolHit({ hit, libraryFileBasename, onReplaced }) {
  // The search response embeds `upscale_match_id`; we synthesise the rest of
  // the shape ReplaceButton needs (it only reads `id`).
  const match = { id: hit.upscale_match_id, status: 'candidate' };
  return (
    <li className="rounded-lg border border-white/10 bg-spotify-mid-gray/30 p-3 flex flex-col gap-2">
      <p className="text-sm text-white font-medium truncate" title={hit.title}>
        {hit.title || <em className="text-spotify-light-gray italic">Untitled</em>}
      </p>
      <p className="text-xs text-spotify-light-gray truncate" title={hit.artist}>
        {hit.artist || '—'}
      </p>
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-wider text-spotify-light-gray/80">
        <span className="px-1.5 py-0.5 rounded bg-spotify-green/20 text-spotify-green font-semibold">
          {hit.bitrate_kbps} kbps
        </span>
        <span>{hit.format}</span>
        {hit.duration_s ? (
          <span>{Math.round(hit.duration_s)}s</span>
        ) : null}
      </div>
      <div className="pt-1">
        <ReplaceButton
          match={match}
          libraryFileBasename={libraryFileBasename}
          onReplaced={onReplaced}
        />
      </div>
    </li>
  );
}

function TriedRow({ row, servedBy }) {
  const isServed = row.slug === servedBy;
  return (
    <li className="flex items-center justify-between text-xs px-3 py-1.5">
      <span className={`flex items-center gap-2 ${isServed ? 'text-spotify-green font-medium' : 'text-spotify-light-gray'}`}>
        <span className={`h-1.5 w-1.5 rounded-full ${isServed ? 'bg-spotify-green' : row.error ? 'bg-red-400' : 'bg-spotify-light-gray/50'}`} aria-hidden />
        {row.slug}
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

function basename(path) {
  if (!path) return '';
  const ix = path.lastIndexOf('/');
  return ix >= 0 ? path.slice(ix + 1) : path;
}

export default React.memo(function MatchResultPanel({ candidate, onClose, onReplaced }) {
  const [state, setState] = useState({ loading: true, result: null, error: null });

  const search = useCallback(async () => {
    setState({ loading: true, result: null, error: null });
    try {
      const result = await api.upscale.search(candidate.id);
      setState({ loading: false, result, error: null });
    } catch (err) {
      setState({ loading: false, result: null, error: err.message });
    }
  }, [candidate.id]);

  useEffect(() => {
    search();
  }, [search]);

  const { loading, result, error } = state;
  const hits = result?.hits || [];
  const tried = result?.tried || [];
  const servedBy = result?.served_by || '';

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

      {/* Tried pools strip — drives the fallback visual */}
      {tried.length > 0 && (
        <ul className="rounded-md bg-spotify-mid-gray/20 border border-white/5 divide-y divide-white/5">
          {tried.map((row) => (
            <TriedRow key={row.slug} row={row} servedBy={servedBy} />
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
        <ul className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
          {hits.map((h) => (
            <PoolHit
              key={h.upscale_match_id}
              hit={h}
              libraryFileBasename={basename(candidate.abs_path)}
              onReplaced={onReplaced}
            />
          ))}
        </ul>
      )}
    </div>
  );
});
