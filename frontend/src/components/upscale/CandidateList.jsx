import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../../api/client';
import CandidateRow from './CandidateRow';
import MatchResultPanel from './MatchResultPanel';
import { SpinnerIcon, ErrorIcon } from '../Icons';

const DEFAULT_LIMIT = 50;

export default React.memo(function CandidateList({ refreshKey = 0, onReplaced }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [threshold, setThreshold] = useState(null);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedId, setExpandedId] = useState(null);

  const load = useCallback(async (nextOffset) => {
    setLoading(true);
    setError(null);
    try {
      const page = await api.upscale.getCandidates({
        limit: DEFAULT_LIMIT,
        offset: nextOffset,
      });
      setItems(page.items || []);
      setTotal(page.total || 0);
      setThreshold(page.threshold_kbps ?? null);
      setOffset(page.offset || 0);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(0);
    setExpandedId(null);
  }, [load, refreshKey]);

  const handleToggle = useCallback((id) => {
    setExpandedId((prev) => (prev === id ? null : id));
  }, []);

  const handlePage = useCallback((delta) => {
    const next = Math.max(0, offset + delta * DEFAULT_LIMIT);
    if (next === offset) return;
    setExpandedId(null);
    load(next);
  }, [load, offset]);

  const pageStart = total === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + items.length, total);

  return (
    <section
      aria-labelledby="upscale-candidates-heading"
      className="rounded-xl border border-white/5 bg-spotify-dark-gray/60 p-5 space-y-3"
    >
      <header className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="upscale-candidates-heading" className="text-base font-semibold text-white">
            Candidates
          </h2>
          <p className="text-xs text-spotify-light-gray mt-0.5">
            Library files at or below{' '}
            <span className="text-white font-medium">{threshold ?? '—'}</span> kbps.
          </p>
        </div>
        {!loading && total > 0 && (
          <p className="text-xs text-spotify-light-gray shrink-0 mt-1">
            <span className="text-white font-medium">{pageStart}</span>–
            <span className="text-white font-medium">{pageEnd}</span>{' '}
            of <span className="text-white font-medium">{total}</span>
          </p>
        )}
      </header>

      {loading ? (
        <div className="flex items-center gap-2 p-4 text-sm text-spotify-light-gray">
          <SpinnerIcon className="w-4 h-4" />
          <span>Loading candidates…</span>
        </div>
      ) : error ? (
        <div className="flex items-start gap-2 p-3 bg-red-900/30 border border-red-500/30 rounded-xl">
          <ErrorIcon className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
          <p className="text-sm text-red-300">{error}</p>
        </div>
      ) : items.length === 0 ? (
        <div className="px-3 py-6 text-center">
          <p className="text-sm text-spotify-light-gray">
            No candidates found{threshold ? <> at or below {threshold} kbps</> : null}.
          </p>
          <p className="text-xs text-spotify-light-gray/70 mt-1">
            Adjust the threshold in Settings, or run a scan to populate the list.
          </p>
        </div>
      ) : (
        <>
          <ul className="rounded-xl bg-spotify-mid-gray/20 border border-white/5">
            {items.map((c) => (
              <React.Fragment key={c.id}>
                <CandidateRow
                  candidate={c}
                  expanded={expandedId === c.id}
                  onToggle={handleToggle}
                />
                {expandedId === c.id && (
                  <li
                    id={`match-${c.id}`}
                    className="border-b border-white/5 last:border-b-0 bg-spotify-black/40 px-3 py-3"
                  >
                    <MatchResultPanel
                      candidate={c}
                      onClose={() => handleToggle(c.id)}
                      onReplaced={onReplaced}
                    />
                  </li>
                )}
              </React.Fragment>
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
