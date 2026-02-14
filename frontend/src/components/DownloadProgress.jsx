export default function DownloadProgress({ downloads, onClear }) {
  if (!downloads || downloads.length === 0) return null;

  const active = downloads.filter(d => d.status === 'downloading');
  const completed = downloads.filter(d => d.status === 'completed');
  const failed = downloads.filter(d => d.status === 'failed');

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 bg-spotify-dark-gray border-t border-white/10 shadow-2xl animate-fade-in">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        {/* Header */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-4">
            <h3 className="text-sm font-semibold text-white">Downloads</h3>
            <div className="flex items-center gap-3 text-xs">
              {active.length > 0 && (
                <span className="text-spotify-green flex items-center gap-1">
                  <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  {active.length} downloading
                </span>
              )}
              {completed.length > 0 && (
                <span className="text-spotify-green">{completed.length} completed</span>
              )}
              {failed.length > 0 && (
                <span className="text-red-400">{failed.length} failed</span>
              )}
            </div>
          </div>
          <button
            onClick={onClear}
            className="text-xs text-spotify-light-gray hover:text-white transition-colors"
          >
            Clear
          </button>
        </div>

        {/* Download List */}
        <div className="max-h-40 overflow-y-auto space-y-2">
          {downloads.map((dl) => (
            <div key={dl.id} className="flex items-center gap-3">
              {dl.status === 'downloading' && (
                <svg className="animate-spin w-4 h-4 text-spotify-green flex-shrink-0" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              {dl.status === 'completed' && (
                <svg className="w-4 h-4 text-spotify-green flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                </svg>
              )}
              {dl.status === 'failed' && (
                <svg className="w-4 h-4 text-red-400 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
                </svg>
              )}
              <div className="min-w-0 flex-1">
                <p className="text-sm text-white truncate">{dl.name}</p>
                <p className="text-xs text-spotify-light-gray truncate">{dl.artist}</p>
              </div>
              <span className={`text-xs font-medium ${
                dl.status === 'downloading' ? 'text-spotify-green' :
                dl.status === 'completed' ? 'text-spotify-green' :
                'text-red-400'
              }`}>
                {dl.status === 'downloading' ? 'Downloading...' :
                 dl.status === 'completed' ? 'Done' :
                 'Failed'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
