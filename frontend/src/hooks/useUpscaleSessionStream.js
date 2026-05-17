import { useEffect, useRef } from 'react';

/**
 * EventSource wrapper for /api/upscale/session-complete.
 *
 * Backend emits exactly one named ``session_complete`` event when the
 * current Upscale session ends (no `confirmed` rows remain AND `replaced`
 * has incremented past the stream's baseline) then closes the stream:
 *
 *   {
 *     type: "session_complete",
 *     replaced: <count for THIS session>,
 *     session_started_at: <iso>,
 *     session_completed_at: <iso>
 *   }
 *
 * The hook reopens the EventSource whenever the parent toggles `enabled`
 * (e.g. after the founder logs into a fresh pool session). It does NOT
 * auto-reconnect after the server closes the stream — the stream closes
 * intentionally once the event has fired.
 */
export function useUpscaleSessionStream({ enabled = true, onSessionComplete } = {}) {
  const callbackRef = useRef(onSessionComplete);
  useEffect(() => { callbackRef.current = onSessionComplete; }, [onSessionComplete]);

  useEffect(() => {
    if (!enabled) return undefined;
    const es = new EventSource('/api/upscale/session-complete');
    const onEvent = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (callbackRef.current) callbackRef.current(data);
      } catch {
        // Malformed payload — drop it; the backend closes the stream after
        // emitting one event so retries aren't useful.
      }
      es.close();
    };
    es.addEventListener('session_complete', onEvent);
    es.onerror = () => {
      // Either a transport drop or the server closing after emitting the
      // event. Don't try to reconnect — the next swap session is what
      // re-arms this stream (parent toggles `enabled`).
      es.close();
    };
    return () => {
      es.removeEventListener('session_complete', onEvent);
      es.close();
    };
  }, [enabled]);
}
