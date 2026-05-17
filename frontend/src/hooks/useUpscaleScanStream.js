import { useEffect, useRef, useState } from 'react';

/**
 * EventSource wrapper for /api/upscale/scan/:id/stream.
 *
 * Backend emits four event shapes (default 'message' events; payload is
 * always `{ type, ... }`):
 *   { type: "start",    root, total }
 *   { type: "progress", scanned, total, candidates, current }
 *   { type: "complete", scanned, candidates, duration_s }
 *   { type: "error",    error }
 *
 * The stream closes itself after `complete` or `error`; we don't auto-retry
 * because re-running a finished scan would be lossy and surprising.
 */
export function useUpscaleScanStream(scanId) {
  const [phase, setPhase] = useState('idle'); // 'idle' | 'scanning' | 'done' | 'error'
  const [scanned, setScanned] = useState(0);
  const [total, setTotal] = useState(0);
  const [candidatesFound, setCandidatesFound] = useState(0);
  const [current, setCurrent] = useState('');
  const [durationS, setDurationS] = useState(null);
  const [error, setError] = useState(null);
  const esRef = useRef(null);

  useEffect(() => {
    if (!scanId) {
      setPhase('idle');
      setScanned(0);
      setTotal(0);
      setCandidatesFound(0);
      setCurrent('');
      setDurationS(null);
      setError(null);
      return undefined;
    }

    const es = new EventSource(`/api/upscale/scan/${scanId}/stream`);
    esRef.current = es;
    setPhase('scanning');
    setError(null);

    es.onmessage = (event) => {
      let data;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      switch (data.type) {
        case 'start':
          setTotal(data.total || 0);
          setScanned(0);
          setCandidatesFound(0);
          break;
        case 'progress':
          setScanned(data.scanned || 0);
          setTotal(data.total || 0);
          setCandidatesFound(data.candidates || 0);
          setCurrent(data.current || '');
          break;
        case 'complete':
          setScanned(data.scanned || 0);
          setCandidatesFound(data.candidates || 0);
          setDurationS(data.duration_s ?? null);
          setPhase('done');
          es.close();
          break;
        case 'error':
          setError(data.error || 'Scan failed');
          setPhase('error');
          es.close();
          break;
        default:
          break;
      }
    };

    es.onerror = () => {
      // Either a transport drop or the server closed normally after
      // emitting 'complete' / 'error'. Don't overwrite a terminal state.
      setPhase((p) => (p === 'scanning' ? 'error' : p));
      setError((e) => e || 'Connection lost during scan');
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [scanId]);

  return { phase, scanned, total, candidatesFound, current, durationS, error };
}
