import { useState, useEffect, useCallback } from 'react';
import Layout from './components/Layout';
import PlaylistInput from './components/PlaylistInput';
import TrackList from './components/TrackList';
import PlaylistMonitor from './components/PlaylistMonitor';
import DownloadProgress from './components/DownloadProgress';
import SettingsModal from './components/SettingsModal';
import { api } from './api/client';
import { useSSE } from './hooks/useSSE';

export default function App() {
  const [playlists, setPlaylists] = useState([]);
  const [selectedPlaylist, setSelectedPlaylist] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState(null);
  const [downloads, setDownloads] = useState([]);
  const [isDownloading, setIsDownloading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);

  // SSE for download progress
  const { data: progressData } = useSSE('/api/downloads/progress', isDownloading);

  useEffect(() => {
    if (progressData) {
      setDownloads(progressData);
      // Check if all done
      const allDone = progressData.every(d => d.status === 'completed' || d.status === 'failed');
      if (allDone && progressData.length > 0) {
        setIsDownloading(false);
        // Refresh playlist to update download status
        if (selectedPlaylist) {
          fetchPlaylist(selectedPlaylist.id);
        }
      }
    }
  }, [progressData]);

  // Load playlists on mount
  useEffect(() => {
    loadPlaylists();
  }, []);

  const loadPlaylists = async () => {
    try {
      const data = await api.getPlaylists();
      setPlaylists(data);
    } catch {
      // API might not be running yet, that's okay
    }
  };

  const fetchPlaylist = async (id) => {
    try {
      const data = await api.getPlaylist(id);
      setSelectedPlaylist(data);
      // Update in playlists list too
      setPlaylists(prev => prev.map(p => p.id === id ? data : p));
    } catch {
      // ignore
    }
  };

  const handleAddPlaylist = async (url) => {
    setLoading(true);
    setError(null);
    try {
      const playlist = await api.addPlaylist(url);
      setPlaylists(prev => [playlist, ...prev]);
      setSelectedPlaylist(playlist);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleRefresh = async () => {
    if (!selectedPlaylist) return;
    setRefreshing(true);
    try {
      const updated = await api.refreshPlaylist(selectedPlaylist.id);
      setSelectedPlaylist(updated);
      setPlaylists(prev => prev.map(p => p.id === updated.id ? updated : p));
    } catch (err) {
      setError(err.message);
    } finally {
      setRefreshing(false);
    }
  };

  const handleDownload = async (trackIds) => {
    try {
      await api.downloadTracks(trackIds);
      setIsDownloading(true);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDownloadAll = async () => {
    if (!selectedPlaylist) return;
    try {
      await api.downloadPlaylist(selectedPlaylist.id);
      setIsDownloading(true);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDownloadNew = async () => {
    if (!selectedPlaylist) return;
    const newTrackIds = selectedPlaylist.tracks
      .filter(t => t.is_new)
      .map(t => t.id);
    if (newTrackIds.length > 0) {
      await handleDownload(newTrackIds);
    }
  };

  const handleCheckAll = async () => {
    setChecking(true);
    try {
      await api.checkAll();
      await loadPlaylists();
      if (selectedPlaylist) {
        await fetchPlaylist(selectedPlaylist.id);
      }
    } catch (err) {
      setError(err.message);
    } finally {
      setChecking(false);
    }
  };

  const handleSelectPlaylist = (playlist) => {
    setSelectedPlaylist(playlist);
  };

  const handleClearProgress = async () => {
    try {
      await api.clearProgress();
      setDownloads([]);
      setIsDownloading(false);
    } catch {
      // ignore
    }
  };

  // Build download status map
  const downloadStatus = {};
  downloads.forEach(d => {
    downloadStatus[d.id] = d;
  });

  return (
    <Layout onOpenSettings={() => setSettingsOpen(true)}>
      {/* Settings Modal */}
      <SettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />

      {/* Playlist Input */}
      <PlaylistInput onSubmit={handleAddPlaylist} loading={loading} />

      {/* Error Message */}
      {error && (
        <div className="mt-4 p-4 bg-red-900/30 border border-red-500/30 rounded-xl flex items-center justify-between animate-fade-in">
          <p className="text-sm text-red-300">{error}</p>
          <button onClick={() => setError(null)} className="text-red-300 hover:text-white">
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
      )}

      {/* Monitored Playlists */}
      <PlaylistMonitor
        playlists={playlists}
        onSelect={handleSelectPlaylist}
        onCheckAll={handleCheckAll}
        selectedId={selectedPlaylist?.id}
        checking={checking}
      />

      {/* Track List */}
      <TrackList
        playlist={selectedPlaylist}
        onDownload={handleDownload}
        onDownloadAll={handleDownloadAll}
        onDownloadNew={handleDownloadNew}
        onRefresh={handleRefresh}
        downloadStatus={downloadStatus}
        refreshing={refreshing}
      />

      {/* Empty State */}
      {!selectedPlaylist && playlists.length === 0 && (
        <div className="mt-16 text-center animate-fade-in">
          <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-spotify-mid-gray flex items-center justify-center">
            <svg className="w-10 h-10 text-spotify-light-gray" fill="currentColor" viewBox="0 0 24 24">
              <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
            </svg>
          </div>
          <h3 className="text-xl font-semibold text-white mb-2">No playlists yet</h3>
          <p className="text-spotify-light-gray max-w-md mx-auto">
            Paste a Spotify playlist URL above to start monitoring and downloading your favorite music.
          </p>
        </div>
      )}

      {/* Download Progress Bar */}
      <DownloadProgress downloads={downloads} onClear={handleClearProgress} />

      {/* Spacer for download bar */}
      {downloads.length > 0 && <div className="h-40" />}
    </Layout>
  );
}
