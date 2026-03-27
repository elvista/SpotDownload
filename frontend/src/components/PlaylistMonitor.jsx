import React from 'react';
import { timeAgo } from '../utils/format';
import { RefreshIcon, MusicIcon, TrashIcon } from './Icons';

function SkeletonCard() {
  return (
    <div className="p-4 rounded-xl bg-spotify-dark-gray animate-pulse">
      <div className="flex items-start gap-3">
        <div className="w-12 h-12 rounded-lg bg-spotify-mid-gray flex-shrink-0" />
        <div className="min-w-0 flex-1 space-y-2">
          <div className="h-4 bg-spotify-mid-gray rounded w-3/4" />
          <div className="h-3 bg-spotify-mid-gray rounded w-1/2" />
          <div className="h-3 bg-spotify-mid-gray rounded w-1/3" />
        </div>
      </div>
    </div>
  );
}

export default React.memo(function PlaylistMonitor({ playlists, onSelect, onDeletePlaylist, onCheckAll, selectedId, checking, loading }) {
  return (
    <div className="animate-fade-in mt-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Monitored Spotify playlists</h2>
        <button
          onClick={onCheckAll}
          disabled={checking || loading}
          className="text-sm text-spotify-green hover:text-spotify-green-dark transition-colors flex items-center gap-1.5 disabled:opacity-50"
        >
          <RefreshIcon className="w-4 h-4" spinning={checking} />
          {checking ? 'Checking...' : 'Check All'}
        </button>
      </div>

      {loading ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3].map((i) => <SkeletonCard key={i} />)}
        </div>
      ) : (!playlists || playlists.length === 0) ? null : (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {playlists.map((pl) => {
          const newCount = pl.tracks?.filter(t => t.is_new).length || 0;
          const isSelected = selectedId === pl.id;

          return (
            <div
              key={pl.id}
              className={`relative text-left p-4 rounded-xl transition-all ${
                isSelected
                  ? 'bg-spotify-mid-gray ring-1 ring-spotify-green'
                  : 'bg-spotify-dark-gray hover:bg-spotify-mid-gray'
              }`}
            >
              <button
                type="button"
                onClick={() => onSelect(pl)}
                className="w-full text-left focus:outline-none"
              >
                <div className="flex items-start gap-3">
                  {pl.image_url ? (
                    <img src={pl.image_url} alt={pl.name} className="w-12 h-12 rounded-lg object-cover flex-shrink-0" />
                  ) : (
                    <div className="w-12 h-12 rounded-lg bg-spotify-mid-gray flex items-center justify-center flex-shrink-0">
                      <MusicIcon className="w-6 h-6 text-spotify-light-gray" />
                    </div>
                  )}
                  <div className="min-w-0 flex-1 pr-8">
                    <p className="text-sm font-medium text-white truncate">{pl.name}</p>
                    <p className="text-xs text-spotify-light-gray mt-0.5">{pl.track_count} tracks</p>
                    <div className="flex items-center gap-2 mt-1.5">
                      <span className="text-xs text-spotify-light-gray">
                        Checked {timeAgo(pl.last_checked)}
                      </span>
                      {newCount > 0 && (
                        <span className="px-1.5 py-0.5 text-[10px] font-bold bg-spotify-green text-black rounded">
                          {newCount} NEW
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              </button>
              {onDeletePlaylist && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDeletePlaylist(pl.id);
                  }}
                  className="absolute top-3 right-3 p-1.5 text-spotify-light-gray hover:text-red-400 hover:bg-white/5 rounded-lg transition-colors"
                  title="Remove from monitoring"
                  aria-label="Remove playlist"
                >
                  <TrashIcon className="w-4 h-4" />
                </button>
              )}
            </div>
          );
        })}
      </div>
      )}
    </div>
  );
});
