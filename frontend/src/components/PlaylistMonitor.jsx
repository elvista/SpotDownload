function timeAgo(dateStr) {
  if (!dateStr) return 'Never';
  const date = new Date(dateStr);
  const now = new Date();
  const seconds = Math.floor((now - date) / 1000);

  if (seconds < 60) return 'Just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function PlaylistMonitor({ playlists, onSelect, onCheckAll, selectedId, checking }) {
  if (!playlists || playlists.length === 0) return null;

  return (
    <div className="animate-fade-in mt-8">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Monitored Playlists</h2>
        <button
          onClick={onCheckAll}
          disabled={checking}
          className="text-sm text-spotify-green hover:text-spotify-green-dark transition-colors flex items-center gap-1.5 disabled:opacity-50"
        >
          <svg className={`w-4 h-4 ${checking ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {checking ? 'Checking...' : 'Check All'}
        </button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {playlists.map((pl) => {
          const newCount = pl.tracks?.filter(t => t.is_new).length || 0;
          const isSelected = selectedId === pl.id;

          return (
            <button
              key={pl.id}
              onClick={() => onSelect(pl)}
              className={`text-left p-4 rounded-xl transition-all ${
                isSelected
                  ? 'bg-spotify-mid-gray ring-1 ring-spotify-green'
                  : 'bg-spotify-dark-gray hover:bg-spotify-mid-gray'
              }`}
            >
              <div className="flex items-start gap-3">
                {pl.image_url ? (
                  <img src={pl.image_url} alt={pl.name} className="w-12 h-12 rounded-lg object-cover flex-shrink-0" />
                ) : (
                  <div className="w-12 h-12 rounded-lg bg-spotify-mid-gray flex items-center justify-center flex-shrink-0">
                    <svg className="w-6 h-6 text-spotify-light-gray" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
                    </svg>
                  </div>
                )}
                <div className="min-w-0 flex-1">
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
          );
        })}
      </div>
    </div>
  );
}
