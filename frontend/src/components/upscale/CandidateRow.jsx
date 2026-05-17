import React from 'react';

function bitrateClass(kbps) {
  if (kbps <= 128) return 'bg-red-900/40 text-red-300 border-red-500/30';
  if (kbps <= 192) return 'bg-amber-900/40 text-amber-200 border-amber-500/30';
  return 'bg-spotify-mid-gray/40 text-spotify-light-gray border-white/10';
}

function basename(path) {
  if (!path) return '';
  const ix = path.lastIndexOf('/');
  return ix >= 0 ? path.slice(ix + 1) : path;
}

function formatDuration(seconds) {
  if (seconds == null) return '';
  const min = Math.floor(seconds / 60);
  const sec = String(Math.round(seconds % 60)).padStart(2, '0');
  return `${min}:${sec}`;
}

export default React.memo(function CandidateRow({ candidate, expanded, onToggle }) {
  const fname = basename(candidate.abs_path);
  const idLabel = candidate.tag_artist || candidate.tag_title
    ? `${candidate.tag_artist ? candidate.tag_artist + ' — ' : ''}${candidate.tag_title || ''}`
    : '';
  return (
    <li className="border-b border-white/5 last:border-b-0">
      <div className="flex items-center gap-3 py-2.5 px-3 hover:bg-white/[0.03] transition-colors">
        <div className="min-w-0 flex-1">
          <p className="text-sm text-white font-medium truncate" title={candidate.abs_path}>
            {fname}
          </p>
          <div className="flex items-center gap-2 text-xs text-spotify-light-gray mt-0.5 min-w-0">
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-semibold border ${bitrateClass(candidate.bitrate_kbps)}`}
            >
              {candidate.bitrate_kbps} kbps
            </span>
            {idLabel ? (
              <span className="truncate" title={idLabel}>{idLabel}</span>
            ) : (
              <span className="italic">No ID3</span>
            )}
            {candidate.duration_s ? (
              <span className="text-spotify-light-gray/70 shrink-0 hidden sm:inline">
                · {formatDuration(candidate.duration_s)}
              </span>
            ) : null}
          </div>
        </div>
        <button
          type="button"
          onClick={() => onToggle(candidate.id)}
          aria-expanded={expanded}
          aria-controls={`match-${candidate.id}`}
          className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors shrink-0 ${
            expanded
              ? 'bg-spotify-green text-black hover:bg-spotify-green-dark'
              : 'bg-spotify-mid-gray text-white hover:bg-white/10'
          }`}
        >
          {expanded ? 'Close' : 'Search'}
        </button>
      </div>
    </li>
  );
});
