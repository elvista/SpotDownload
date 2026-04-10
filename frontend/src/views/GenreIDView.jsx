import { useState, useEffect, useRef, useCallback } from 'react';
import { api } from '../api/client';

const DEFAULT_DB_PATH = '~/Library/Application Support/Lexicon/main.db';
const PAGE_SIZE = 50;

export default function GenreIDView() {
  const [dbStatus, setDbStatus] = useState(null);
  const [dbPath, setDbPath] = useState(DEFAULT_DB_PATH);
  const [error, setError] = useState('');

  // Library browsing state
  const [tracks, setTracks] = useState([]);
  const [totalTracks, setTotalTracks] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('all'); // 'all' | 'empty'
  const searchTimerRef = useRef(null);

  // Scan state — overlays onto the library table
  const [scanning, setScanning] = useState(false);
  const [scanProgress, setScanProgress] = useState({ current: 0, total: 0 });
  const [scanResults, setScanResults] = useState({}); // {trackId: {genre}}
  const [currentLookup, setCurrentLookup] = useState(null); // track currently being looked up
  const eventSourceRef = useRef(null);

  // Review state (after scan)
  const [reviewMode, setReviewMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [editedGenres, setEditedGenres] = useState({});

  // Staged state
  const [stagedTracks, setStagedTracks] = useState([]);
  const [showStaged, setShowStaged] = useState(false);

  // Export state
  const [exporting, setExporting] = useState(false);
  const [exportResult, setExportResult] = useState(null);

  // --- Data loading ---

  const loadDbStatus = useCallback(async () => {
    try {
      const status = await api.getGenreIdDbStatus();
      setDbStatus(status);
      if (status.valid && status.path) setDbPath(status.path);
    } catch {
      setDbStatus({ valid: false, error: 'Could not check Lexicon database' });
    }
  }, []);

  const loadTracks = useCallback(async (p = page, s = search, f = filter) => {
    if (!dbStatus?.valid) return;
    try {
      const data = await api.getGenreIdTracks({ search: s, page: p, pageSize: PAGE_SIZE, filter: f });
      setTracks(data.tracks);
      setTotalTracks(data.total);
    } catch (e) {
      setError(e.message);
    }
  }, [dbStatus, page, search, filter]);

  const loadStaged = useCallback(async () => {
    try {
      const rows = await api.getStaged();
      setStagedTracks(rows);
      if (rows.length > 0) setShowStaged(true);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => {
    loadDbStatus();
    loadStaged();
  }, [loadDbStatus, loadStaged]);

  useEffect(() => {
    if (dbStatus?.valid) loadTracks();
  }, [dbStatus, page, filter]);

  // Debounced search
  const handleSearchChange = (value) => {
    setSearch(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    searchTimerRef.current = setTimeout(() => {
      setPage(1);
      loadTracks(1, value, filter);
    }, 300);
  };

  const handleSetDbPath = async () => {
    setError('');
    try {
      const result = await api.setGenreIdDbPath(dbPath);
      setDbStatus(result);
    } catch (e) {
      setError(e.message);
    }
  };

  // --- Scanning ---

  const handleScan = async (rescan = false) => {
    setError('');
    setScanResults({});
    setScanProgress({ current: 0, total: 0 });
    setCurrentLookup(null);
    setSelectedIds(new Set());
    setEditedGenres({});
    setReviewMode(false);

    try {
      const { sessionId, totalTracks: total, message } = await api.scanGenres({ rescan });
      if (!sessionId) {
        setError(message || 'No tracks to scan');
        return;
      }

      setScanProgress({ current: 0, total });
      setScanning(true);

      const es = new EventSource(`/api/genreid/stream/${sessionId}`);
      eventSourceRef.current = es;

      es.onmessage = (event) => {
        const data = JSON.parse(event.data);

        if (data.type === 'lookup') {
          setCurrentLookup(data.track);
          setScanProgress({ current: data.current, total: data.total });
        } else if (data.type === 'progress') {
          setScanProgress({ current: data.current, total: data.total });
          if (data.suggestedGenre) {
            const result = {
              genre: data.suggestedGenre,
              artist: data.track.artist,
              title: data.track.title,
              remixer: data.track.remixer || '',
              key: data.track.key || '',
            };
            setScanResults((prev) => ({ ...prev, [data.track.id]: result }));
            setSelectedIds((prev) => new Set([...prev, data.track.id]));
          }
          if (data.error) {
            setError(`API error: ${data.error}`);
          }
        } else if (data.type === 'complete') {
          es.close();
          eventSourceRef.current = null;
          setScanning(false);
          setCurrentLookup(null);
          setReviewMode(true);
        } else if (data.type === 'error') {
          es.close();
          eventSourceRef.current = null;
          setError(data.error);
          setScanning(false);
          setCurrentLookup(null);
          if (Object.keys(scanResults).length > 0) setReviewMode(true);
        }
      };

      es.onerror = () => {
        es.close();
        eventSourceRef.current = null;
        setScanning(false);
        if (Object.keys(scanResults).length > 0) setReviewMode(true);
      };
    } catch (e) {
      setError(e.message);
      setScanning(false);
    }
  };

  // --- Review actions ---

  const toggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAllScanned = () => {
    const scannedIds = Object.keys(scanResults).map(Number);
    if (selectedIds.size === scannedIds.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(scannedIds));
    }
  };

  const getGenre = (trackId) => {
    if (editedGenres[trackId] !== undefined) return editedGenres[trackId];
    if (scanResults[trackId]) return scanResults[trackId].genre;
    return '';
  };

  const handleApprove = async () => {
    setError('');
    const selected = [...selectedIds]
      .filter((id) => scanResults[id])
      .map((id) => ({
        trackId: id,
        title: scanResults[id].title,
        artist: scanResults[id].artist,
        genre: getGenre(id),
      }));

    if (selected.length === 0) {
      setError('No tracks selected');
      return;
    }

    try {
      await api.approveGenres(selected);
      await loadStaged();
      setReviewMode(false);
      setScanResults({});
      setShowStaged(true);
    } catch (e) {
      setError(e.message);
    }
  };

  const handleExport = async () => {
    setError('');
    setExportResult(null);
    setExporting(true);
    try {
      const result = await api.exportToLexicon();
      setExportResult(result);
      setStagedTracks([]);
      setShowStaged(false);
      await loadDbStatus();
      await loadTracks();
    } catch (e) {
      setError(e.message);
    } finally {
      setExporting(false);
    }
  };

  const handleClearStaged = async () => {
    try {
      await api.clearStaged();
      setStagedTracks([]);
      setShowStaged(false);
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) eventSourceRef.current.close();
    };
  }, []);

  // --- Helpers ---

  const totalPages = Math.ceil(totalTracks / PAGE_SIZE);
  const scannedCount = Object.keys(scanResults).length;

  // Merge scan results into current page tracks
  const getTrackGenreDisplay = (track) => {
    if (scanResults[track.id]) {
      return {
        genre: editedGenres[track.id] !== undefined ? editedGenres[track.id] : scanResults[track.id].genre,
        isScanned: true,
      };
    }
    return { genre: track.genre || '', isScanned: false };
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white mb-1">Genre ID</h1>
        <p className="text-sm text-spotify-light-gray">
          Browse your Lexicon library and classify tracks with empty genres.
        </p>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg p-4 text-red-400 text-sm">
          {error}
          <button
            onClick={() => setError('')}
            className="ml-3 text-red-300 hover:text-white transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}

      {exportResult && (
        <div className="bg-spotify-green/10 border border-spotify-green/20 rounded-lg p-4 text-spotify-green text-sm">
          Exported {exportResult.exported} genre{exportResult.exported !== 1 ? 's' : ''} to Lexicon.
          <button
            onClick={() => setExportResult(null)}
            className="ml-3 text-spotify-green/70 hover:text-white transition-colors"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* DB Status */}
      <div className="bg-spotify-dark-gray rounded-lg p-5 space-y-3">
        <h2 className="text-sm font-semibold text-white uppercase tracking-wider">Lexicon Database</h2>
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={dbPath}
            onChange={(e) => setDbPath(e.target.value)}
            className="flex-1 bg-spotify-black border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-spotify-light-gray/50 focus:outline-none focus:ring-2 focus:ring-spotify-green"
            placeholder="Path to Lexicon main.db"
          />
          <button
            onClick={handleSetDbPath}
            className="px-4 py-2 bg-white/10 hover:bg-white/15 text-white text-sm rounded-lg transition-colors"
          >
            Set Path
          </button>
        </div>
        {dbStatus && (
          <div className="text-sm">
            {dbStatus.valid ? (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4 text-spotify-light-gray">
                  <span className="flex items-center gap-1.5">
                    <div className="h-2 w-2 rounded-full bg-spotify-green" />
                    Connected
                  </span>
                  <span>{dbStatus.totalTracks?.toLocaleString()} tracks</span>
                  <span className="text-amber-400">{dbStatus.emptyGenres?.toLocaleString()} empty genres</span>
                </div>
                {!scanning && (
                  <div className="flex items-center gap-2">
                    {dbStatus.emptyGenres > 0 && (
                      <button
                        onClick={() => handleScan(false)}
                        className="px-4 py-2 bg-spotify-green hover:bg-spotify-green/90 text-black font-semibold text-sm rounded-lg transition-colors whitespace-nowrap"
                      >
                        Scan {dbStatus.emptyGenres.toLocaleString()} Empty
                      </button>
                    )}
                    <button
                      onClick={() => handleScan(true)}
                      className="px-4 py-2 bg-white/10 hover:bg-white/15 text-white text-sm rounded-lg transition-colors whitespace-nowrap"
                    >
                      Rescan All
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <span className="text-red-400">{dbStatus.error}</span>
            )}
          </div>
        )}
      </div>

      {/* Staged Tracks Banner */}
      {showStaged && stagedTracks.length > 0 && (
        <div className="bg-spotify-dark-gray rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">
              {stagedTracks.length} track{stagedTracks.length !== 1 ? 's' : ''} staged for export
            </h2>
            <div className="flex items-center gap-3">
              <button
                onClick={() => setShowStaged(false)}
                className="text-xs text-spotify-light-gray hover:text-white transition-colors"
              >
                Hide
              </button>
              <button
                onClick={handleClearStaged}
                className="px-3 py-1.5 bg-white/10 hover:bg-white/15 text-white text-xs rounded-lg transition-colors"
              >
                Clear
              </button>
              <button
                onClick={handleExport}
                disabled={exporting}
                className="px-3 py-1.5 bg-spotify-green hover:bg-spotify-green/90 disabled:opacity-40 text-black font-semibold text-xs rounded-lg transition-colors"
              >
                {exporting ? 'Exporting...' : 'Export to Lexicon'}
              </button>
            </div>
          </div>
          <div className="max-h-32 overflow-y-auto">
            <div className="flex flex-wrap gap-1.5">
              {stagedTracks.map((t) => (
                <span key={t.id} className="text-xs bg-white/5 rounded px-2 py-1 text-spotify-light-gray">
                  {t.artist} — {t.title} <span className="text-spotify-green ml-1">{t.genre}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Scanning Progress */}
      {scanning && (
        <div className="bg-spotify-dark-gray rounded-lg p-5 space-y-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-white font-medium">Looking up genres on Last.fm...</span>
            <span className="text-spotify-light-gray">
              {scanProgress.current} / {scanProgress.total}
            </span>
          </div>
          <div className="w-full bg-spotify-black rounded-full h-2">
            <div
              className="bg-spotify-green h-2 rounded-full transition-all duration-300"
              style={{
                width: `${scanProgress.total ? (scanProgress.current / scanProgress.total) * 100 : 0}%`,
              }}
            />
          </div>
          {currentLookup && (
            <div className="text-sm text-spotify-light-gray/70 truncate">
              <span className="text-white">{currentLookup.artist}</span>
              {currentLookup.title && (
                <span> — {currentLookup.title}</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Review Bar */}
      {reviewMode && scannedCount > 0 && (
        <div className="bg-purple-500/10 border border-purple-500/20 rounded-lg p-4 flex items-center justify-between">
          <span className="text-sm text-purple-300">
            {scannedCount} genre{scannedCount !== 1 ? 's' : ''} classified ({selectedIds.size} selected)
          </span>
          <div className="flex items-center gap-3">
            <button
              onClick={toggleAllScanned}
              className="text-xs text-spotify-light-gray hover:text-white transition-colors"
            >
              {selectedIds.size === scannedCount ? 'Deselect All' : 'Select All'}
            </button>
            <button
              onClick={() => { setReviewMode(false); setScanResults({}); setSelectedIds(new Set()); setEditedGenres({}); }}
              className="px-3 py-1.5 bg-white/10 hover:bg-white/15 text-white text-xs rounded-lg transition-colors"
            >
              Dismiss
            </button>
            <button
              onClick={handleApprove}
              disabled={selectedIds.size === 0}
              className="px-3 py-1.5 bg-spotify-green hover:bg-spotify-green/90 disabled:opacity-40 disabled:cursor-not-allowed text-black font-semibold text-xs rounded-lg transition-colors"
            >
              Approve Selected
            </button>
          </div>
        </div>
      )}

      {/* Library Table */}
      {dbStatus?.valid && (
        <div className="space-y-3">
          {/* Search + Filter + Scan */}
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={search}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search by artist or title..."
              className="flex-1 bg-spotify-dark-gray border border-white/10 rounded-lg px-3 py-2 text-sm text-white placeholder-spotify-light-gray/50 focus:outline-none focus:ring-2 focus:ring-spotify-green"
            />
            <div className="flex rounded-lg overflow-hidden border border-white/10">
              <button
                onClick={() => { setFilter('all'); setPage(1); }}
                className={`px-3 py-2 text-xs font-medium transition-colors ${
                  filter === 'all' ? 'bg-white/15 text-white' : 'bg-spotify-dark-gray text-spotify-light-gray hover:text-white'
                }`}
              >
                All
              </button>
              <button
                onClick={() => { setFilter('empty'); setPage(1); }}
                className={`px-3 py-2 text-xs font-medium transition-colors ${
                  filter === 'empty' ? 'bg-white/15 text-white' : 'bg-spotify-dark-gray text-spotify-light-gray hover:text-white'
                }`}
              >
                Empty Genres
              </button>
            </div>
            {dbStatus.emptyGenres > 0 && !scanning && (
              <button
                onClick={handleScan}
                className="px-4 py-2 bg-spotify-green hover:bg-spotify-green/90 text-black font-semibold text-sm rounded-lg transition-colors whitespace-nowrap"
              >
                Scan {dbStatus.emptyGenres.toLocaleString()} Empty
              </button>
            )}
          </div>

          {/* Track Table */}
          <div className="bg-spotify-dark-gray rounded-lg overflow-hidden">
            <div className="max-h-[60vh] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-spotify-dark-gray z-10">
                  <tr className="text-left text-spotify-light-gray border-b border-white/5">
                    {reviewMode && <th className="p-3 w-10" />}
                    <th className="p-3">Artist</th>
                    <th className="p-3">Title</th>
                    <th className="p-3">Genre</th>
                  </tr>
                </thead>
                <tbody>
                  {tracks.map((track) => {
                    const { genre, isScanned } = getTrackGenreDisplay(track);
                    const isSelected = selectedIds.has(track.id);
                    return (
                      <tr
                        key={track.id}
                        className={`border-b border-white/5 transition-colors ${
                          isScanned && isSelected ? 'bg-white/5' : 'hover:bg-white/[0.02]'
                        }`}
                      >
                        {reviewMode && (
                          <td className="p-3">
                            {isScanned ? (
                              <input
                                type="checkbox"
                                checked={isSelected}
                                onChange={() => toggleSelect(track.id)}
                                className="rounded accent-spotify-green"
                              />
                            ) : null}
                          </td>
                        )}
                        <td className="p-3 text-white">{track.artist}</td>
                        <td className="p-3 text-spotify-light-gray">
                          {track.title}
                          {track.remixer && (
                            <span className="text-spotify-light-gray/50 ml-1">({track.remixer})</span>
                          )}
                        </td>
                        <td className="p-3">
                          {isScanned && reviewMode ? (
                            <input
                              type="text"
                              value={genre}
                              onChange={(e) => setEditedGenres((prev) => ({ ...prev, [track.id]: e.target.value }))}
                              className="w-full bg-spotify-black border border-white/10 rounded px-2 py-1 text-sm text-spotify-green focus:outline-none focus:ring-1 focus:ring-spotify-green"
                            />
                          ) : (
                            <span className={genre ? 'text-spotify-light-gray' : 'text-spotify-light-gray/30 italic'}>
                              {genre || 'Empty'}
                            </span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {tracks.length === 0 && (
                    <tr>
                      <td colSpan={reviewMode ? 7 : 6} className="p-8 text-center text-spotify-light-gray/50 text-sm">
                        {search ? 'No tracks match your search.' : 'No tracks found.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between text-sm text-spotify-light-gray">
              <span>
                {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, totalTracks).toLocaleString()} of {totalTracks.toLocaleString()}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page === 1}
                  className="px-3 py-1.5 bg-white/10 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-white text-xs rounded-lg transition-colors"
                >
                  Previous
                </button>
                <span className="text-xs">
                  Page {page} of {totalPages}
                </span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page === totalPages}
                  className="px-3 py-1.5 bg-white/10 hover:bg-white/15 disabled:opacity-30 disabled:cursor-not-allowed text-white text-xs rounded-lg transition-colors"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
