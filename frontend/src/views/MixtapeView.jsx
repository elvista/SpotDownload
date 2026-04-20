import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import DownloadProgress from '../components/DownloadProgress';
import { useSSE } from '../hooks/useSSE';

const API = '/api/mixtape';
const STUCK_THRESHOLD_MS = 30000;
const STUCK_SAME_PERCENT_MS = 30000;

function normalizeTrackId(artist, title) {
  const normalize = (str) => {
    if (!str) return '';
    return str
      .toLowerCase()
      .replace(/\(.*?\)/g, '')
      .replace(/\[.*?\]/g, '')
      .replace(/feat\.|ft\.|featuring/gi, '')
      .replace(/&/g, 'and')
      .replace(/[^a-z0-9]/g, '')
      .trim();
  };
  return `${normalize(artist)}-${normalize(title)}`;
}

function parseTimestamp(ts) {
  if (!ts || typeof ts !== 'string') return 0;
  const parts = ts.split(':');
  if (parts.length === 2) {
    return parseInt(parts[0], 10) * 60 + parseInt(parts[1], 10);
  }
  if (parts.length === 3) {
    return parseInt(parts[0], 10) * 3600 + parseInt(parts[1], 10) * 60 + parseInt(parts[2], 10);
  }
  return 0;
}

function formatElapsed(ms) {
  const totalSec = Math.floor(ms / 1000);
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return min > 0 ? `${min}m ${sec.toString().padStart(2, '0')}s` : `${sec}s`;
}

function getConfidenceLevel(confidence) {
  if (confidence >= 0.7) return 'high';
  if (confidence >= 0.4) return 'medium';
  return 'low';
}

function detectUrlType(url) {
  if (url.includes('youtube.com') || url.includes('youtu.be')) return 'youtube';
  if (url.includes('soundcloud.com')) return 'soundcloud';
  if (url.includes('mixcloud.com')) return 'mixcloud';
  return null;
}

function sanitizeFilename(filename) {
  return filename
    .replace(/[<>:"/\\|?*]/g, '')
    .replace(/\s+/g, '_')
    .substring(0, 200);
}

function getTimeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatApiErrorBody(data) {
  if (!data || typeof data !== 'object') return '';
  if (typeof data.error === 'string' && data.error) return data.error;
  const d = data.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) {
    return d.map((x) => (typeof x === 'object' && x?.msg ? x.msg : JSON.stringify(x))).join(', ');
  }
  return '';
}

function SpotifyIcon({ className }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor" aria-hidden>
      <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
    </svg>
  );
}

export default function MixtapeView() {
  const [phase, setPhase] = useState('upload');
  const [urlInput, setUrlInput] = useState('');
  const [dragOver, setDragOver] = useState(false);
  const [progressPct, setProgressPct] = useState(0);
  const [progressStatus, setProgressStatus] = useState('');
  const [progressEta, setProgressEta] = useState('');
  const [progressElapsed, setProgressElapsed] = useState('');
  const [stuckWarning, setStuckWarning] = useState('');
  const [tracks, setTracks] = useState([]);
  const [mixtapeName, setMixtapeName] = useState('mixtape');
  const [filter, setFilter] = useState('all');
  const [errorMessage, setErrorMessage] = useState('');
  const [lastFile, setLastFile] = useState(null);
  const [showBottomProgress, setShowBottomProgress] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [downloads, setDownloads] = useState([]);
  const [isDownloading, setIsDownloading] = useState(false);
  const [fingerprintStatus, setFingerprintStatus] = useState(null);

  const { data: downloadProgressData } = useSSE('/api/downloads/progress', isDownloading);

  const eventSourceRef = useRef(null);
  const progressStartRef = useRef(null);
  const timerRef = useRef(null);
  const stuckTimerRef = useRef(null);
  const lastUpdateRef = useRef(null);
  const lastPctRef = useRef(-1);
  const lastPctChangeRef = useRef(null);
  const progressFillRef = useRef(null);
  const processingRef = useRef(false);

  const currentSongsRef = useRef([]);

  useEffect(() => {
    document.title = 'Mixtape ID — CrateDigger';
    return () => { document.title = 'CrateDigger'; };
  }, []);

  const checkLastFile = useCallback(async () => {
    try {
      const response = await fetch(`${API}/last-file`);
      const data = await response.json();
      if (data.available) {
        setLastFile({ name: data.name, date: data.date, size: data.size });
      } else {
        setLastFile(null);
      }
    } catch {
      setLastFile(null);
    }
  }, []);

  const loadFingerprintStatus = useCallback(async () => {
    try {
      const r = await fetch(`${API}/fingerprint-status`);
      if (r.ok) {
        setFingerprintStatus(await r.json());
      }
    } catch {
      setFingerprintStatus(null);
    }
  }, []);

  useEffect(() => {
    checkLastFile();
    loadFingerprintStatus();
  }, [checkLastFile, loadFingerprintStatus]);

  useEffect(() => {
    if (downloadProgressData) {
      setDownloads(downloadProgressData);
      const allDone = downloadProgressData.every(
        (d) => d.status === 'completed' || d.status === 'failed'
      );
      if (allDone && downloadProgressData.length > 0) {
        setIsDownloading(false);
      }
    }
  }, [downloadProgressData]);

  const stopProgressTimer = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (stuckTimerRef.current) {
      clearInterval(stuckTimerRef.current);
      stuckTimerRef.current = null;
    }
    setStuckWarning('');
  }, []);

  const startProgressTimer = useCallback(() => {
    stopProgressTimer();
    progressStartRef.current = Date.now();
    lastUpdateRef.current = Date.now();
    lastPctChangeRef.current = Date.now();
    lastPctRef.current = -1;

    timerRef.current = setInterval(() => {
      const elapsed = Date.now() - progressStartRef.current;
      setProgressElapsed(`Elapsed: ${formatElapsed(elapsed)}`);
    }, 1000);

    stuckTimerRef.current = setInterval(() => {
      const sinceLast = Date.now() - lastUpdateRef.current;
      const sinceChange = Date.now() - lastPctChangeRef.current;
      if (sinceLast > STUCK_THRESHOLD_MS) {
        setStuckWarning(`No updates for ${Math.round(sinceLast / 1000)}s — processing may be stalled`);
      } else if (sinceChange > STUCK_SAME_PERCENT_MS && lastPctRef.current > 0) {
        setStuckWarning(`Stuck at ${Math.round(lastPctRef.current)}% — a segment may be timing out`);
      }
    }, 5000);
  }, [stopProgressTimer]);

  const onProgressUpdate = useCallback((pct) => {
    lastUpdateRef.current = Date.now();
    if (Math.round(pct) !== Math.round(lastPctRef.current)) {
      lastPctChangeRef.current = Date.now();
      lastPctRef.current = pct;
      setStuckWarning('');
    }
    const etaEl = progressStartRef.current && pct > 2;
    if (etaEl) {
      const elapsed = Date.now() - progressStartRef.current;
      const estimatedTotal = elapsed / (pct / 100);
      const remaining = estimatedTotal - elapsed;
      if (remaining > 0 && remaining < 3600000) {
        setProgressEta(`ETA: ${formatElapsed(remaining)}`);
      } else {
        setProgressEta('');
      }
    }
  }, []);

  const handleStreamClose = useCallback(() => {
    if (eventSourceRef.current) {
      try {
        eventSourceRef.current.close();
      } catch { /* ignore */ }
      eventSourceRef.current = null;
    }
  }, []);

  const mergeTrack = useCallback((song, isFinal = false) => {
    const id = normalizeTrackId(song.artist, song.title);
    setTracks((prev) => {
      const idx = prev.findIndex((t) => normalizeTrackId(t.artist, t.title) === id);
      const merged = {
        ...song,
        key: id,
        isFinal,
        timestamp: song.timestamp,
      };
      if (idx === -1) {
        currentSongsRef.current = [...currentSongsRef.current, merged];
        return [...prev, merged].sort((a, b) => parseTimestamp(a.timestamp) - parseTimestamp(b.timestamp));
      }
      const cur = prev[idx];
      const nextConf = (song.confidence ?? 0) > (cur.confidence ?? 0) ? song : cur;
      const next = { ...cur, ...nextConf, ...merged, isFinal: isFinal || cur.isFinal };
      const copy = [...prev];
      copy[idx] = next;
      currentSongsRef.current = copy;
      return copy.sort((a, b) => parseTimestamp(a.timestamp) - parseTimestamp(b.timestamp));
    });
  }, []);

  const handleStreamMessage = useCallback(
    (data) => {
      switch (data.type) {
        case 'download': {
          const dlPct = data.percent != null ? Math.round(data.percent) : null;
          let dlStatus = 'Downloading audio...';
          if (dlPct != null) {
            dlStatus += ` ${dlPct}%`;
            if (data.totalSize) dlStatus += ` of ${data.totalSize}`;
          } else if (data.totalSize) {
            dlStatus += ` ${data.totalSize}`;
          }
          if (data.speed) dlStatus += ` (${data.speed})`;
          if (data.eta) dlStatus += ` — ETA ${data.eta}`;
          const p = dlPct != null ? dlPct * 0.95 : 0;
          setProgressPct(p);
          setProgressStatus(dlStatus);
          onProgressUpdate(p);
          break;
        }
        case 'init': {
          if (data.mixtapeName) {
            setMixtapeName(data.mixtapeName);
          }
          setProgressPct(0);
          setProgressStatus(`Starting analysis (${Math.round(data.duration / 60)} min audio)...`);
          checkLastFile();
          break;
        }
        case 'pass':
          setProgressStatus(`Scan — ${data.description}`);
          break;
        case 'step': {
          const stepLabels = {
            segmenting: 'Extracting',
            fingerprinting: 'Fingerprinting',
            matching: data.matched ? 'Matched' : 'No match',
          };
          const stepRange = { min: 0, max: 95 };
          const stepPct =
            stepRange.min +
            (data.segment / data.totalSegments) * (stepRange.max - stepRange.min);
          setProgressPct(stepPct);
          setProgressStatus(
            `${stepLabels[data.step] || data.step} at ${data.timestamp} (${data.segment}/${data.totalSegments})`
          );
          onProgressUpdate(stepPct);
          break;
        }
        case 'progress': {
          const rangeBasic = { min: 0, max: 95 };
          const pct =
            rangeBasic.min +
            (data.current / data.total) * (rangeBasic.max - rangeBasic.min);
          const pos = data.audioDuration ? ` (${data.timestamp} / ${data.audioDuration})` : ` at ${data.timestamp}`;
          setProgressPct(pct);
          setProgressStatus(`Samples ${data.current}/${data.total}${pos}`);
          onProgressUpdate(pct);
          break;
        }
        case 'sample-error':
          setStuckWarning(
            `Segment ${data.segment}/${data.totalSegments} failed at ${data.timestamp}: ${data.error}`
          );
          break;
        case 'song':
          mergeTrack(data.song, false);
          setPhase('results');
          break;
        case 'final-track':
          mergeTrack(data.track, true);
          break;
        case 'complete': {
          stopProgressTimer();
          const totalElapsed = progressStartRef.current
            ? formatElapsed(Date.now() - progressStartRef.current)
            : '';
          setProgressPct(100);
          setProgressStatus(
            `Complete! Found ${data.totalSongs} tracks (${data.totalSamples} samples analyzed)${
              totalElapsed ? ` in ${totalElapsed}` : ''
            }`
          );
          setProcessing(false);
          processingRef.current = false;
          setTimeout(() => {
            setShowBottomProgress(false);
          }, 2000);
          handleStreamClose();
          break;
        }
        case 'error': {
          stopProgressTimer();
          const msg = typeof data.error === 'string' ? data.error : data.error || 'An error occurred';
          if (data.fingerprintStatus) {
            setFingerprintStatus(data.fingerprintStatus);
          }
          setErrorMessage(msg);
          setProcessing(false);
          processingRef.current = false;
          setPhase('error');
          checkLastFile();
          handleStreamClose();
          break;
        }
        default:
          break;
      }
    },
    [checkLastFile, handleStreamClose, mergeTrack, onProgressUpdate, stopProgressTimer]
  );

  const connectToStream = useCallback(
    (sessionId) => {
      handleStreamClose();
      currentSongsRef.current = [];
      setTracks([]);
      startProgressTimer();
      setPhase('results');
      setShowBottomProgress(true);
      setProgressPct(0);
      setProgressStatus('Initializing...');
      setProcessing(true);
      processingRef.current = true;

      const es = new EventSource(`${API}/stream/${sessionId}`);
      eventSourceRef.current = es;
      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          handleStreamMessage(data);
        } catch (e) {
          console.error(e);
        }
      };
      es.onerror = () => {
        handleStreamClose();
        setTimeout(() => {
          if (processingRef.current) {
            setErrorMessage('Connection lost. Please try again.');
            setPhase('error');
            setProcessing(false);
            processingRef.current = false;
          }
        }, 1000);
      };
    },
    [handleStreamClose, handleStreamMessage, startProgressTimer]
  );

  const handleFileUpload = async (file) => {
    setPhase('upload');
    setShowBottomProgress(true);
    setProgressPct(0);
    setProgressStatus('Uploading file...');
    startProgressTimer();

    const formData = new FormData();
    formData.append('audio', file);

    try {
      const response = await fetch(`${API}/upload`, { method: 'POST', body: formData });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Upload failed');
      if (data.success && data.sessionId) {
        connectToStream(data.sessionId);
      } else {
        throw new Error('No session ID received');
      }
    } catch (err) {
      console.error(err);
      stopProgressTimer();
      setShowBottomProgress(false);
      setErrorMessage(err.message);
      setPhase('error');
      toast.error(err.message);
    }
  };

  const handleLinkProcessing = async (url, type) => {
    setShowBottomProgress(true);
    setProgressPct(0);
    setProgressStatus('Downloading audio...');
    startProgressTimer();

    try {
      const response = await fetch(`${API}/process-link`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, type }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Processing failed');
      if (data.success && data.sessionId) {
        connectToStream(data.sessionId);
      } else {
        throw new Error('No session ID received');
      }
    } catch (err) {
      console.error(err);
      stopProgressTimer();
      setShowBottomProgress(false);
      setErrorMessage(err.message);
      setPhase('error');
      toast.error(err.message);
    }
  };

  const handleRescan = async () => {
    setShowBottomProgress(true);
    setProgressPct(0);
    setProgressStatus('Starting rescan...');
    startProgressTimer();
    try {
      const response = await fetch(`${API}/rescan`, { method: 'POST' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Rescan failed');
      if (data.success && data.sessionId) {
        connectToStream(data.sessionId);
      } else {
        throw new Error('No session ID received');
      }
    } catch (err) {
      stopProgressTimer();
      setShowBottomProgress(false);
      setErrorMessage(err.message);
      setPhase('error');
      toast.error(err.message);
    }
  };

  const visibleTracks = tracks.filter((t) => {
    const c = t.confidence ?? 0;
    if (filter === 'all') return true;
    if (filter === 'high-medium') return c >= 0.4;
    if (filter === 'high') return c >= 0.7;
    return true;
  });

  const exportAsText = () => {
    if (visibleTracks.length === 0) {
      toast.error('No songs to export');
      return;
    }
    let text = '';
    visibleTracks.forEach((song) => {
      const ts = song.timestamp ? `[${song.timestamp}] ` : '';
      const meta = [];
      if (song.bpm) meta.push(`${Math.round(song.bpm)} BPM`);
      if (song.key) meta.push(song.key);
      const metaStr = meta.length ? ` (${meta.join(', ')})` : '';
      text += `${ts}${song.artist} - ${song.title}${metaStr}\n`;
    });
    const blob = new Blob([text], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${sanitizeFilename(mixtapeName)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success('Download started');
  };

  const handleClearDownloadProgress = useCallback(async () => {
    try {
      await fetch('/api/downloads/progress', { method: 'DELETE' });
    } catch {
      /* ignore */
    }
    setDownloads([]);
    setIsDownloading(false);
  }, []);

  const downloadFoundTracks = async () => {
    if (visibleTracks.length === 0) {
      toast.error('No tracks to download');
      return;
    }
    const ok = window.confirm(
      `Download ${visibleTracks.length} tracks via YouTube search (same flow as Spotify ID)? Files go to your configured download folder.`
    );
    if (!ok) return;
    try {
      setDownloads([]);
      setIsDownloading(true);
      const res = await fetch('/api/downloads', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mixtape_tracks: visibleTracks.map((song) => ({
            name: song.title,
            artist: song.artist,
          })),
        }),
      });
      const raw = await res.text();
      let errBody = {};
      if (raw) {
        try {
          errBody = JSON.parse(raw);
        } catch {
          errBody = { detail: raw };
        }
      }
      if (!res.ok) {
        const d = errBody.detail;
        const detailStr =
          typeof d === 'string'
            ? d
            : Array.isArray(d)
              ? d.map((x) => x.msg || JSON.stringify(x)).join(', ')
              : d
                ? JSON.stringify(d)
                : '';
        throw new Error(detailStr || errBody.message || 'Download failed');
      }
      toast.success('Download started');
    } catch (err) {
      toast.error(err.message || 'Download failed');
      setIsDownloading(false);
    }
  };

  const exportToSpotify = async () => {
    if (visibleTracks.length === 0) {
      toast.error('No visible tracks to export');
      return;
    }

    try {
      const st = await fetch(`${API}/spotify/status`);
      if (st.ok) {
        const s = await st.json();
        if (!s.clientConfigured) {
          toast.error('Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env');
          return;
        }
      }
    } catch { /* continue */ }

    const ok = window.confirm(
      `Create Spotify playlist from ${visibleTracks.length} visible tracks?\n\nTracks are matched by artist and title.`
    );
    if (!ok) return;

    try {
      const body = {
        tracks: visibleTracks.map((song) => ({
          artist: song.artist,
          title: song.title,
          spotifyLink: song.spotifyLink || null,
        })),
        playlistName: mixtapeName || `Mixtape — ${new Date().toLocaleDateString()}`,
        filter,
      };
      const response = await fetch(`${API}/create-spotify-playlist`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const raw = await response.text();
      let data = {};
      if (raw) {
        try {
          data = JSON.parse(raw);
        } catch {
          throw new Error(`Invalid response (HTTP ${response.status})`);
        }
      }
      if (!response.ok) {
        if (data.needsSpotifyAuth) {
          toast.info('Connect Spotify under Settings on Spotify ID (gear icon).');
          return;
        }
        throw new Error(formatApiErrorBody(data) || 'Failed to create playlist');
      }
      if (data.playlistUrl) {
        const openNow = window.confirm(`Playlist created (${data.addedTracks} tracks). Open in Spotify?`);
        if (openNow) window.open(data.playlistUrl, '_blank');
      } else {
        toast.success('Playlist created');
      }
    } catch (err) {
      toast.error(err.message);
    }
  };

  const resetUpload = () => {
    stopProgressTimer();
    handleStreamClose();
    processingRef.current = false;
    setPhase('upload');
    setTracks([]);
    setErrorMessage('');
    setShowBottomProgress(false);
    setProcessing(false);
    setUrlInput('');
  };

  useEffect(() => () => {
    stopProgressTimer();
    handleStreamClose();
  }, [handleStreamClose, stopProgressTimer]);

  const showUploadPanel = phase === 'upload' || (phase === 'error' && !processing);

  return (
    <div className="animate-fade-in space-y-8 pb-32">
      <div>
        <h2 className="text-lg font-semibold text-white">Mixtape ID</h2>
        <p className="text-sm text-spotify-light-gray mt-1 max-w-2xl">
          Upload MP3/WAV/M4A or paste a YouTube, SoundCloud, or Mixcloud link. We sample the mix and fingerprint segments
          to build a timestamped track list (ACRCloud / AudD).
        </p>
      </div>

      {fingerprintStatus && !fingerprintStatus.canIdentify && (
        <div
          className="rounded-xl border border-amber-500/35 bg-amber-950/35 px-4 py-3 text-sm text-amber-100"
          role="alert"
        >
          <p className="font-medium text-amber-50">Fingerprinting APIs are not configured</p>
          <p className="mt-1 text-amber-100/90">
            Add <strong>ACRCloud</strong> (ACRCLOUD_HOST, ACRCLOUD_ACCESS_KEY, ACRCLOUD_ACCESS_SECRET) and/or{' '}
            <strong>AUDD_API_TOKEN</strong> to the repo-root <code className="rounded bg-black/30 px-1 text-xs">.env</code>
            , then restart the backend. Copy from <code className="rounded bg-black/30 px-1 text-xs">.env.example</code>.
          </p>
          {Array.isArray(fingerprintStatus.hints) && fingerprintStatus.hints.length > 0 && (
            <ul className="mt-2 list-inside list-disc text-xs text-amber-200/85">
              {fingerprintStatus.hints.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      {showUploadPanel && (
        <section className="rounded-2xl border border-white/10 bg-spotify-mid-gray/40 p-6 space-y-6">
          <h3 className="text-base font-medium text-white">Process mixtape</h3>
          <div className="flex flex-col sm:flex-row gap-3">
            <input
              type="text"
              value={urlInput}
              onChange={(e) => setUrlInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const t = detectUrlType(urlInput.trim());
                  if (t) handleLinkProcessing(urlInput.trim(), t);
                  else toast.error('Enter a valid YouTube, SoundCloud, or Mixcloud URL');
                }
              }}
              placeholder="Paste YouTube, SoundCloud, or Mixcloud URL"
              className="flex-1 rounded-xl bg-spotify-black border border-white/10 px-4 py-3 text-white placeholder:text-spotify-light-gray/60 focus:outline-none focus:ring-2 focus:ring-spotify-green"
            />
            <button
              type="button"
              onClick={() => {
                const t = detectUrlType(urlInput.trim());
                if (t) handleLinkProcessing(urlInput.trim(), t);
                else toast.error('Invalid URL');
              }}
              className="px-6 py-3 rounded-xl bg-spotify-green text-black font-semibold hover:brightness-110 transition-all"
            >
              Analyze
            </button>
          </div>

          <div className="relative flex items-center gap-4">
            <div className="flex-1 h-px bg-white/10" />
            <span className="text-xs text-spotify-light-gray">or</span>
            <div className="flex-1 h-px bg-white/10" />
          </div>

          <div
            role="button"
            tabIndex={0}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') document.getElementById('mixtape-file')?.click();
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              const f = e.dataTransfer.files?.[0];
              if (f) handleFileUpload(f);
            }}
            onClick={() => document.getElementById('mixtape-file')?.click()}
            className={`rounded-2xl border-2 border-dashed px-8 py-12 text-center cursor-pointer transition-colors ${
              dragOver ? 'border-spotify-green bg-spotify-green/10' : 'border-white/20 hover:border-white/40'
            }`}
          >
            <p className="text-spotify-light-gray text-sm mb-2">Drag and drop an audio file, or click to browse</p>
            <p className="text-xs text-spotify-light-gray/70">MP3, WAV, M4A up to 500MB</p>
            <input
              id="mixtape-file"
              type="file"
              accept=".mp3,.wav,.m4a"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) handleFileUpload(f);
                e.target.value = '';
              }}
            />
          </div>

          {lastFile && (
            <button
              type="button"
              onClick={handleRescan}
              className="w-full sm:w-auto px-4 py-2 rounded-lg border border-white/15 text-sm text-spotify-light-gray hover:text-white hover:bg-white/5"
            >
              Rescan: <strong className="text-white">{lastFile.name}</strong>
              <span className="text-spotify-light-gray/80">
                {' '}
                ({(lastFile.size / 1024 / 1024).toFixed(1)} MB · {getTimeAgo(lastFile.date)})
              </span>
            </button>
          )}
        </section>
      )}

      {phase === 'error' && errorMessage && (
        <div className="p-4 rounded-xl bg-red-900/30 border border-red-500/30 text-red-200 text-sm">
          {errorMessage}
          <button type="button" className="ml-4 underline" onClick={resetUpload}>
            Dismiss
          </button>
        </div>
      )}

      {(phase === 'results' || tracks.length > 0) && (
        <section className="rounded-2xl border border-white/10 bg-spotify-mid-gray/30 p-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-4">
            <div>
              <h3 className="text-white font-medium">{mixtapeName}</h3>
              <p className="text-sm text-spotify-light-gray">{visibleTracks.length} tracks shown</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {['all', 'high-medium', 'high'].map((f) => (
                <button
                  key={f}
                  type="button"
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                    filter === f
                      ? 'bg-spotify-green text-black'
                      : 'bg-white/5 text-spotify-light-gray hover:bg-white/10'
                  }`}
                >
                  {f === 'all' ? 'All finds' : f === 'high-medium' ? 'Medium+' : 'High only'}
                </button>
              ))}
            </div>
          </div>

          <div className="flex flex-wrap gap-2 mb-6">
            <button
              type="button"
              onClick={exportAsText}
              className="px-4 py-2 rounded-lg bg-white/10 text-sm text-white hover:bg-white/15"
            >
              Export text
            </button>
            <button
              type="button"
              onClick={exportToSpotify}
              className="px-4 py-2 rounded-lg bg-spotify-green text-black text-sm font-semibold hover:brightness-110 flex items-center gap-2"
            >
              <SpotifyIcon className="w-4 h-4" />
              Import to Spotify
            </button>
            <button
              type="button"
              onClick={downloadFoundTracks}
              disabled={processing}
              className="px-4 py-2 rounded-lg bg-white/15 text-sm text-white hover:bg-white/20 disabled:opacity-50"
            >
              Download found tracks
            </button>
            <button
              type="button"
              onClick={resetUpload}
              className="px-4 py-2 rounded-lg border border-white/15 text-sm text-spotify-light-gray hover:text-white"
            >
              New analysis
            </button>
          </div>

          <ul className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
            {visibleTracks.map((song) => {
              const conf = song.confidence ?? 0;
              const level = getConfidenceLevel(conf);
              const spotifyUrl =
                song.spotifyLink ||
                `https://open.spotify.com/search/${encodeURIComponent(`${song.artist} ${song.title}`)}`;
              return (
                <li
                  key={song.key || `${song.artist}-${song.title}-${song.timestamp}`}
                  className="flex flex-col sm:flex-row sm:items-start gap-4 p-4 rounded-xl bg-spotify-black/50 border border-white/5"
                >
                  <div className="text-spotify-green font-mono text-sm shrink-0 w-16">{song.timestamp}</div>
                  <div className="flex-1 min-w-0">
                    <div className="text-white font-medium truncate">{song.title}</div>
                    <div className="text-sm text-spotify-light-gray mt-1">
                      {song.artist}
                      {song.album ? ` · ${song.album}` : ''}
                    </div>
                    <div className="flex flex-wrap gap-2 mt-2 text-xs">
                      <span className="text-spotify-light-gray/80">{song.service}</span>
                      <span
                        className={
                          level === 'high'
                            ? 'text-green-400'
                            : level === 'medium'
                              ? 'text-yellow-400/90'
                              : 'text-orange-400/90'
                        }
                      >
                        {Math.round(conf * 100)}%
                      </span>
                      {song.warnings?.length > 0 && (
                        <span title={song.warnings.join(', ')} className="text-amber-400">
                          Warning
                        </span>
                      )}
                    </div>
                  </div>
                  <a
                    href={spotifyUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="shrink-0 p-2 rounded-lg bg-white/10 text-spotify-green hover:bg-white/15"
                    title="Open in Spotify"
                  >
                    <SpotifyIcon className="w-5 h-5" />
                  </a>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {downloads.length > 0 && (
        <DownloadProgress
          downloads={downloads}
          onClear={handleClearDownloadProgress}
          className="z-[60]"
        />
      )}

      {showBottomProgress && (
        <div className="fixed bottom-0 left-0 right-0 z-40 border-t border-white/10 bg-spotify-black/95 backdrop-blur-md px-4 py-3">
          <div className="max-w-7xl mx-auto">
            <div className="flex items-center justify-between text-xs text-spotify-light-gray mb-1">
              <span>{progressElapsed}</span>
              <span>{progressEta}</span>
            </div>
            <div className="h-2 rounded-full bg-white/10 overflow-hidden" ref={progressFillRef}>
              <div
                className="h-full bg-spotify-green transition-[width] duration-300 ease-out"
                style={{ width: `${Math.min(100, Math.max(0, progressPct))}%` }}
              />
            </div>
            <p className="text-sm text-white mt-2 truncate">{progressStatus}</p>
            {stuckWarning && <p className="text-xs text-amber-400 mt-1">{stuckWarning}</p>}
          </div>
        </div>
      )}
    </div>
  );
}
