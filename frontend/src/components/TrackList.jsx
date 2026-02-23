import React, { useMemo, useState } from 'react';
import TrackRow from './TrackRow';
import { DownloadIcon, PlusIcon, RefreshIcon, MusicIcon, BackIcon, TrashIcon } from './Icons';

export default React.memo(function TrackList({ playlist, onDownload, onDownloadAll, onDownloadNew, onRefresh, onGoHome, onRemovePlaylist, downloadStatus, refreshing }) {
  const [searchQuery, setSearchQuery] = useState('');

  const tracks = playlist?.tracks ?? [];
  const newTracks = useMemo(() => tracks.filter(t => t.is_new), [tracks]);
  const downloadedCount = useMemo(() => tracks.filter(t => t.is_downloaded).length, [tracks]);
  const filteredTracks = useMemo(() => {
    let list = tracks;
    if (searchQuery.trim()) {
      const q = searchQuery.trim().toLowerCase();
      list = list.filter(t =>
        (t.name && t.name.toLowerCase().includes(q)) ||
        (t.artist && t.artist.toLowerCase().includes(q)) ||
        (t.album && t.album.toLowerCase().includes(q))
      );
    }
    // Undownloaded tracks first, then downloaded (stable sort)
    list = [...list].sort((a, b) =>
      a.is_downloaded === b.is_downloaded ? 0 : a.is_downloaded ? 1 : -1
    );
    return list;
  }, [tracks, searchQuery]);

  if (!playlist) return null;

  return (
    <div className="animate-fade-in mt-8">
      {/* Back bar */}
      {(onGoHome || onRemovePlaylist) && (
        <div className="flex items-center justify-between gap-4 mb-6">
          {onGoHome && (
            <button
              type="button"
              onClick={onGoHome}
              className="flex items-center gap-2 text-spotify-light-gray hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-spotify-green focus:ring-offset-2 focus:ring-offset-spotify-black rounded-lg px-2 py-1 -ml-2"
            >
              <BackIcon className="w-5 h-5" />
              <span>Back to playlists</span>
            </button>
          )}
          {onRemovePlaylist && (
            <button
              type="button"
              onClick={() => {
                if (window.confirm('Remove this playlist from monitoring?')) {
                  onRemovePlaylist(playlist.id);
                  onGoHome?.();
                }
              }}
              className="flex items-center gap-2 text-spotify-light-gray hover:text-red-400 transition-colors focus:outline-none focus:ring-2 focus:ring-red-500/50 rounded-lg px-3 py-1.5"
              title="Remove from monitoring"
            >
              <TrashIcon className="w-4 h-4" />
              <span>Remove from monitoring</span>
            </button>
          )}
        </div>
      )}

      {/* Playlist Header */}
      <div className="flex flex-col sm:flex-row gap-6 mb-8">
        {playlist.image_url ? (
          <img src={playlist.image_url} alt={playlist.name} className="w-48 h-48 rounded-xl object-cover shadow-2xl flex-shrink-0" />
        ) : (
          <div className="w-48 h-48 rounded-xl bg-spotify-mid-gray flex items-center justify-center flex-shrink-0">
            <MusicIcon className="w-16 h-16 text-spotify-light-gray" />
          </div>
        )}
        <div className="flex flex-col justify-end">
          <span className="text-xs uppercase tracking-widest text-spotify-light-gray font-medium mb-1">Playlist</span>
          <h2 className="text-3xl sm:text-4xl font-bold text-white mb-2">{playlist.name}</h2>
          {playlist.description && (
            <p className="text-sm text-spotify-light-gray mb-3 line-clamp-2">{playlist.description}</p>
          )}
          <div className="flex items-center gap-3 text-sm text-spotify-light-gray">
            <span className="font-medium text-white">{playlist.owner}</span>
            <span>&middot;</span>
            <span>{playlist.track_count} songs</span>
            <span>&middot;</span>
            <span>{downloadedCount} downloaded</span>
            {newTracks.length > 0 && (
              <>
                <span>&middot;</span>
                <span className="text-spotify-green font-medium">{newTracks.length} new</span>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Action Bar */}
      <div className="flex flex-wrap items-center gap-3 mb-6">
        <button onClick={onDownloadAll} className="px-5 py-2.5 bg-spotify-green hover:bg-spotify-green-dark text-black font-semibold rounded-full transition-all flex items-center gap-2">
          <DownloadIcon /> Download All
        </button>
        {newTracks.length > 0 && (
          <button onClick={onDownloadNew} className="px-5 py-2.5 bg-transparent border border-spotify-green text-spotify-green hover:bg-spotify-green hover:text-black font-semibold rounded-full transition-all flex items-center gap-2">
            <PlusIcon /> Download New ({newTracks.length})
          </button>
        )}
        <button onClick={onRefresh} disabled={refreshing} className="px-5 py-2.5 bg-spotify-mid-gray hover:bg-white/10 text-white font-medium rounded-full transition-all flex items-center gap-2 disabled:opacity-50">
          <RefreshIcon spinning={refreshing} />
          {refreshing ? 'Checking...' : 'Check for Changes'}
        </button>
      </div>

      {/* Search */}
      <div className="mb-4">
        <input
          type="search"
          placeholder="Search tracks by title, artist, album..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="w-full max-w-md px-4 py-2 bg-spotify-mid-gray border border-white/10 rounded-xl text-white placeholder-gray-500 text-sm focus:outline-none focus:border-spotify-green"
        />
      </div>

      {/* Track Table */}
      <div className="bg-spotify-dark-gray/50 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-white/5">
              <th className="text-left py-3 px-4 text-xs font-medium text-spotify-light-gray uppercase tracking-wider w-12">#</th>
              <th className="text-left py-3 px-4 text-xs font-medium text-spotify-light-gray uppercase tracking-wider">Title</th>
              <th className="text-left py-3 px-4 text-xs font-medium text-spotify-light-gray uppercase tracking-wider hidden md:table-cell">Album</th>
              <th className="text-left py-3 px-4 text-xs font-medium text-spotify-light-gray uppercase tracking-wider w-20 hidden sm:table-cell">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </th>
              <th className="w-20"></th>
            </tr>
          </thead>
          <tbody>
            {filteredTracks.map((track, index) => (
              <TrackRow
                key={track.id}
                track={track}
                index={index}
                onDownload={onDownload}
                downloadStatus={downloadStatus}
              />
            ))}
          </tbody>
        </table>
        {filteredTracks.length === 0 && (
          <div className="py-12 text-center text-spotify-light-gray">
            <p>No tracks found in this playlist.</p>
          </div>
        )}
      </div>
    </div>
  );
});
