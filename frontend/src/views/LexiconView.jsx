import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import PlaylistTree from '../components/PlaylistTree';

const DEFAULT_DB_PATH = '~/Library/Application Support/Lexicon/main.db';

export default function LexiconView() {
  const [dbStatus, setDbStatus] = useState(null);
  const [dbPathInput, setDbPathInput] = useState('');
  const [playlists, setPlaylists] = useState([]);
  const [selectedPlaylist, setSelectedPlaylist] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [loadingTracks, setLoadingTracks] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importProgress, setImportProgress] = useState(null);
  const [importResult, setImportResult] = useState(null);
  const [error, setError] = useState(null);

  const esRef = useRef(null);

  // Load DB status on mount
  useEffect(() => {
    api.getLexiconDbStatus().then((status) => {
      setDbStatus(status);
      setDbPathInput(status.path || DEFAULT_DB_PATH);
      if (status.valid) {
        loadPlaylists();
      }
    }).catch((err) => setError(err.message));
  }, []);

  const loadPlaylists = useCallback(async () => {
    try {
      const data = await api.getLexiconPlaylists();
      setPlaylists(data.playlists || []);
    } catch (err) {
      setError(err.message);
    }
  }, []);

  const handleSetPath = useCallback(async () => {
    setError(null);
    try {
      const result = await api.setLexiconDbPath(dbPathInput);
      setDbStatus({ configured: true, ...result });
      if (result.valid) {
        await loadPlaylists();
      }
    } catch (err) {
      setError(err.message);
    }
  }, [dbPathInput, loadPlaylists]);

  const handleSelectPlaylist = useCallback(async (playlist) => {
    setSelectedPlaylist(playlist);
    setTracks([]);
    setImportResult(null);
    setImportProgress(null);
    setLoadingTracks(true);
    try {
      const data = await api.getLexiconPlaylistTracks(playlist.id);
      setTracks(data.tracks || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingTracks(false);
    }
  }, []);

  const handleImport = useCallback(async () => {
    if (!selectedPlaylist) return;
    setError(null);
    setImportResult(null);
    setImportProgress(null);

    try {
      const spotifyStatus = await api.getLexiconSpotifyStatus();
      if (!spotifyStatus.clientConfigured) {
        setError('Spotify API credentials not configured. Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env.');
        return;
      }
      if (!spotifyStatus.hasRefreshToken) {
        setError('Connect Spotify first: open Spotify ID (home), click the gear (Settings), and connect your account.');
        return;
      }
    } catch (err) {
      setError(err.message);
      return;
    }

    setImporting(true);
    try {
      const { sessionId } = await api.importLexiconToSpotify(
        selectedPlaylist.id,
        selectedPlaylist.name,
      );

      // Connect SSE
      const es = new EventSource(`/api/lexicon/import-stream/${sessionId}`);
      esRef.current = es;

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setImportProgress(data);
          if (data.type === 'complete') {
            setImportResult(data);
            setImporting(false);
            es.close();
          } else if (data.type === 'error') {
            setError(data.error);
            setImporting(false);
            es.close();
          }
        } catch {
          // ignore parse errors
        }
      };

      es.onerror = () => {
        setImporting(false);
        es.close();
      };
    } catch (err) {
      setError(err.message);
      setImporting(false);
    }
  }, [selectedPlaylist]);

  // Cleanup SSE on unmount
  useEffect(() => {
    return () => {
      if (esRef.current) {
        esRef.current.close();
      }
    };
  }, []);

  const progressPercent =
    importProgress?.current && importProgress?.total
      ? Math.round((importProgress.current / importProgress.total) * 100)
      : 0;

  return (
    <div className="flex gap-6 h-[calc(100vh-12rem)]">
      {/* Left sidebar */}
      <div className="w-72 shrink-0 flex flex-col gap-4 overflow-y-auto">
        {/* DB path config */}
        <div className="bg-white/5 rounded-xl p-4 border border-white/5">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-spotify-light-gray/70 mb-3">
            Lexicon Database
          </h3>
          <div className="flex gap-2">
            <input
              type="text"
              value={dbPathInput}
              onChange={(e) => setDbPathInput(e.target.value)}
              placeholder={DEFAULT_DB_PATH}
              className="flex-1 bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm text-white placeholder-spotify-light-gray/40 focus:outline-none focus:border-spotify-green/50 min-w-0"
            />
            <button
              type="button"
              onClick={handleSetPath}
              className="px-3 py-1.5 bg-spotify-green text-black text-sm font-medium rounded-lg hover:bg-spotify-green/90 transition-colors shrink-0"
            >
              Set
            </button>
          </div>
          {dbStatus && !dbStatus.valid && (
            <p className="text-xs text-red-400 mt-2">{dbStatus.error}</p>
          )}
          {dbStatus?.valid && (
            <p className="text-xs text-spotify-green/70 mt-2">Connected</p>
          )}
        </div>

        {/* Playlist tree */}
        {dbStatus?.valid && (
          <div className="flex-1 overflow-y-auto">
            <h3 className="text-xs font-semibold uppercase tracking-wider text-spotify-light-gray/70 mb-2 px-2">
              Playlists
            </h3>
            <PlaylistTree
              playlists={playlists}
              selectedId={selectedPlaylist?.id}
              onSelect={handleSelectPlaylist}
            />
          </div>
        )}
      </div>

      {/* Right content */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {error && (
          <div className="bg-red-500/10 border border-red-500/20 rounded-xl p-4 mb-4">
            <p className="text-sm text-red-400">{error}</p>
            <button
              type="button"
              onClick={() => setError(null)}
              className="text-xs text-red-400/60 hover:text-red-400 mt-1"
            >
              Dismiss
            </button>
          </div>
        )}

        {!selectedPlaylist && dbStatus?.valid && (
          <div className="flex items-center justify-center h-full text-spotify-light-gray/40 text-sm">
            Select a playlist from the sidebar
          </div>
        )}

        {!dbStatus?.valid && !error && (
          <div className="flex items-center justify-center h-full text-spotify-light-gray/40 text-sm">
            Set your Lexicon database path to get started
          </div>
        )}

        {selectedPlaylist && (
          <div>
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-xl font-bold text-white">{selectedPlaylist.name}</h2>
                <p className="text-sm text-spotify-light-gray/60 mt-0.5">
                  {tracks.length} track{tracks.length !== 1 ? 's' : ''}
                </p>
              </div>
              <button
                type="button"
                onClick={handleImport}
                disabled={importing || !tracks.length}
                className="px-4 py-2 rounded-lg bg-spotify-green text-black text-sm font-semibold hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                  <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
                </svg>
                {importing ? 'Importing...' : 'Import to Spotify'}
              </button>
            </div>

            {/* Import progress */}
            {importing && importProgress && (
              <div className="bg-white/5 rounded-xl p-4 border border-white/5 mb-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm text-white">
                    {importProgress.type === 'matching' || importProgress.type === 'matched'
                      ? `Matching tracks... ${importProgress.current}/${importProgress.total}`
                      : importProgress.type === 'creating_playlist'
                        ? `${importProgress.mode === 'update' ? 'Updating' : 'Creating'} playlist...`
                        : importProgress.type === 'adding_tracks'
                          ? `Adding tracks... ${importProgress.added}/${importProgress.total}`
                          : 'Processing...'}
                  </span>
                  <span className="text-xs text-spotify-light-gray/60">{progressPercent}%</span>
                </div>
                <div className="w-full bg-white/10 rounded-full h-1.5">
                  <div
                    className="bg-spotify-green h-1.5 rounded-full transition-all duration-300"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
                {(importProgress.type === 'matching' || importProgress.type === 'matched') && importProgress.artist && (
                  <p className="text-xs text-spotify-light-gray/60 mt-2 truncate">
                    {importProgress.artist} — {importProgress.title}
                    {importProgress.status === 'found' && (
                      <span className="text-spotify-green ml-2">matched</span>
                    )}
                    {importProgress.status === 'not_found' && (
                      <span className="text-red-400 ml-2">not found</span>
                    )}
                  </p>
                )}
              </div>
            )}

            {/* Import result */}
            {importResult && (
              <div className="bg-spotify-green/10 border border-spotify-green/20 rounded-xl p-4 mb-4">
                <p className="text-sm text-white font-medium mb-1">
                  {importResult.mode === 'update' ? 'Playlist updated!' : 'Playlist created!'}
                </p>
                <p className="text-xs text-spotify-light-gray/80">
                  {importResult.matched} matched, {importResult.notMatched} not found, {importResult.added} added
                </p>
                {importResult.playlistUrl && (
                  <a
                    href={importResult.playlistUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-block mt-2 text-sm text-spotify-green hover:underline"
                  >
                    Open in Spotify
                  </a>
                )}
              </div>
            )}

            {/* Track list */}
            {loadingTracks ? (
              <div className="text-sm text-spotify-light-gray/40">Loading tracks...</div>
            ) : (
              <div className="space-y-0.5">
                {tracks.map((track, i) => {
                  const spotifySearch = `https://open.spotify.com/search/${encodeURIComponent(`${track.artist || ''} ${track.title || ''}`.trim())}`;
                  return (
                    <a
                      key={i}
                      href={spotifySearch}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-white/5 transition-colors group cursor-pointer"
                    >
                      <span className="text-xs text-spotify-light-gray/40 w-8 text-right shrink-0">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm text-white truncate group-hover:text-spotify-green transition-colors">{track.title || 'Untitled'}</p>
                        <p className="text-xs text-spotify-light-gray/60 truncate">{track.artist || 'Unknown Artist'}</p>
                      </div>
                      <svg className="w-4 h-4 shrink-0 text-spotify-light-gray/30 group-hover:text-spotify-green transition-colors" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
                      </svg>
                    </a>
                  );
                })}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
