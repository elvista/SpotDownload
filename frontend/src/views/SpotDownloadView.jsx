import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { toast } from 'sonner';
import PlaylistInput from '../components/PlaylistInput';
import TrackList from '../components/TrackList';
import PlaylistMonitor from '../components/PlaylistMonitor';
import DownloadProgress from '../components/DownloadProgress';
import { CloseIcon, MusicIcon } from '../components/Icons';
import { api } from '../api/client';
import { useSSE } from '../hooks/useSSE';
import { useHeaderContext } from '../context/HeaderContext';

/** Map API/network errors to user-friendly messages. */
function getErrorMessage(err, fallback = 'Something went wrong') {
  const msg = err?.message || String(err);
  if (/401|Unauthorized|token|expired/i.test(msg)) return 'Spotify session expired. Reconnect in Settings.';
  if (/403|Forbidden/i.test(msg)) return 'Access denied. Check Spotify connection in Settings.';
  if (/404|not found/i.test(msg)) return msg;
  if (/fetch|network|ECONNREFUSED|Failed to fetch/i.test(msg)) return 'Backend may be offline. Start the server and try again.';
  return msg || fallback;
}

export default function SpotDownloadView() {
  const { setOnGoHome } = useHeaderContext();
  const [playlists, setPlaylists] = useState([]);
  const [playlistsLoading, setPlaylistsLoading] = useState(true);
  const [selectedPlaylist, setSelectedPlaylist] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState(null);
  const [downloads, setDownloads] = useState([]);
  const [isDownloading, setIsDownloading] = useState(false);

  const selectedPlaylistIdRef = useRef(null);
  selectedPlaylistIdRef.current = selectedPlaylist?.id ?? null;

  const { data: progressData } = useSSE('/api/downloads/progress', isDownloading);

  const fetchPlaylist = useCallback(async (id) => {
    try {
      const data = await api.getPlaylist(id);
      setSelectedPlaylist(data);
      setPlaylists(prev => prev.map(p => p.id === id ? data : p));
    } catch (err) {
      toast.error(getErrorMessage(err, 'Could not load playlist'));
    }
  }, []);

  const loadPlaylists = useCallback(async () => {
    setPlaylistsLoading(true);
    try {
      const data = await api.getPlaylists();
      setPlaylists(data);
    } catch (err) {
      toast.error(getErrorMessage(err, 'Could not load playlists. Is the backend running?'));
    } finally {
      setPlaylistsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (progressData) {
      setDownloads(progressData);
      const allDone = progressData.every(d => d.status === 'completed' || d.status === 'failed');
      if (allDone && progressData.length > 0) {
        setIsDownloading(false);
        const currentId = selectedPlaylistIdRef.current;
        if (currentId) fetchPlaylist(currentId);
      }
    }
  }, [progressData, fetchPlaylist]);

  useEffect(() => {
    loadPlaylists();
  }, [loadPlaylists]);

  useEffect(() => {
    document.title = 'Spotify ID — Music Studio';
  }, []);

  useEffect(() => {
    setOnGoHome(
      selectedPlaylist ? () => {
        setSelectedPlaylist(null);
      } : undefined
    );
    return () => setOnGoHome(undefined);
  }, [selectedPlaylist, setOnGoHome]);

  const handleAddPlaylist = useCallback(async (url) => {
    setLoading(true);
    setError(null);
    try {
      const playlist = await api.addPlaylist(url);
      setPlaylists(prev => [playlist, ...prev]);
      setSelectedPlaylist(playlist);
    } catch (err) {
      if (err.existingPlaylist) {
        await loadPlaylists();
        setSelectedPlaylist(err.existingPlaylist);
        toast.success('This playlist is already in your list.');
      } else {
        const msg = getErrorMessage(err);
        setError(msg);
        toast.error(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [loadPlaylists]);

  const handleRefresh = useCallback(async () => {
    const id = selectedPlaylistIdRef.current;
    if (!id) return;
    setRefreshing(true);
    try {
      const updated = await api.refreshPlaylist(id);
      setSelectedPlaylist(updated);
      setPlaylists(prev => prev.map(p => p.id === updated.id ? updated : p));
    } catch (err) {
      const msg = getErrorMessage(err);
      setError(msg);
      toast.error(msg);
    } finally {
      setRefreshing(false);
    }
  }, []);

  const handleDownload = useCallback(async (trackIds) => {
    try {
      await api.downloadTracks(trackIds);
      setIsDownloading(true);
    } catch (err) {
      const msg = getErrorMessage(err);
      setError(msg);
      toast.error(msg);
    }
  }, []);

  const handleDownloadAll = useCallback(async () => {
    const id = selectedPlaylistIdRef.current;
    if (!id) return;
    try {
      await api.downloadPlaylist(id);
      setIsDownloading(true);
    } catch (err) {
      const msg = getErrorMessage(err);
      setError(msg);
      toast.error(msg);
    }
  }, []);

  const handleDownloadNew = useCallback(async () => {
    if (!selectedPlaylist) return;
    const newTrackIds = selectedPlaylist.tracks
      .filter(t => t.is_new)
      .map(t => t.id);
    if (newTrackIds.length > 0) {
      try {
        await api.downloadTracks(newTrackIds);
        setIsDownloading(true);
      } catch (err) {
        const msg = getErrorMessage(err);
        setError(msg);
        toast.error(msg);
      }
    }
  }, [selectedPlaylist]);

  const handleCheckAll = useCallback(async () => {
    setChecking(true);
    try {
      await api.checkAll();
      await loadPlaylists();
      const currentId = selectedPlaylistIdRef.current;
      if (currentId) await fetchPlaylist(currentId);
    } catch (err) {
      const msg = getErrorMessage(err);
      setError(msg);
      toast.error(msg);
    } finally {
      setChecking(false);
    }
  }, [loadPlaylists, fetchPlaylist]);

  const handleSelectPlaylist = useCallback((playlist) => {
    setSelectedPlaylist(playlist);
  }, []);

  const handleGoHome = useCallback(() => {
    setSelectedPlaylist(null);
  }, []);

  const handleDeletePlaylist = useCallback(async (id) => {
    if (!window.confirm('Remove this playlist from monitoring?')) return;
    try {
      await api.deletePlaylist(id);
      setPlaylists(prev => prev.filter(p => p.id !== id));
      if (selectedPlaylistIdRef.current === id) setSelectedPlaylist(null);
      toast.success('Playlist removed');
    } catch (err) {
      toast.error(getErrorMessage(err, 'Could not remove playlist'));
    }
  }, []);

  const handleClearProgress = useCallback(async () => {
    try {
      await api.clearProgress();
      setDownloads([]);
      setIsDownloading(false);
    } catch (err) {
      toast.error(getErrorMessage(err, 'Could not clear progress'));
    }
  }, []);

  const handleClearError = useCallback(() => setError(null), []);

  const downloadStatus = useMemo(() => {
    const status = {};
    downloads.forEach(d => { status[d.id] = d; });
    return status;
  }, [downloads]);

  return (
    <>
      {selectedPlaylist ? (
        <TrackList
          playlist={selectedPlaylist}
          onDownload={handleDownload}
          onDownloadAll={handleDownloadAll}
          onDownloadNew={handleDownloadNew}
          onRefresh={handleRefresh}
          onGoHome={handleGoHome}
          onRemovePlaylist={handleDeletePlaylist}
          downloadStatus={downloadStatus}
          refreshing={refreshing}
        />
      ) : (
        <>
          <PlaylistInput onSubmit={handleAddPlaylist} loading={loading} />

          {error && (
            <div className="mt-4 p-4 bg-red-900/30 border border-red-500/30 rounded-xl flex items-center justify-between animate-fade-in">
              <p className="text-sm text-red-300">{error}</p>
              <button type="button" onClick={handleClearError} className="text-red-300 hover:text-white">
                <CloseIcon />
              </button>
            </div>
          )}

          <PlaylistMonitor
            playlists={playlists}
            onSelect={handleSelectPlaylist}
            onDeletePlaylist={handleDeletePlaylist}
            onCheckAll={handleCheckAll}
            selectedId={selectedPlaylist?.id}
            checking={checking}
            loading={playlistsLoading}
          />

          {playlists.length === 0 && (
            <div className="mt-16 text-center animate-fade-in">
              <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-spotify-mid-gray flex items-center justify-center">
                <MusicIcon className="w-10 h-10 text-spotify-light-gray" />
              </div>
              <h3 className="text-xl font-semibold text-white mb-2">No playlists yet</h3>
              <p className="text-spotify-light-gray max-w-md mx-auto">
                Paste a Spotify playlist URL above to start monitoring and downloading tracks (Spotify ID).
              </p>
            </div>
          )}
        </>
      )}

      <DownloadProgress downloads={downloads} onClear={handleClearProgress} />
      {downloads.length > 0 && <div className="h-40" />}
    </>
  );
}
