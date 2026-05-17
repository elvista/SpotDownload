import { useCallback } from 'react';
import { toast } from 'sonner';
import { useUpscaleSessionStream } from '../../hooks/useUpscaleSessionStream';

const SEEN_KEY = 'upscale.lastSessionCompletedAt';

function loadSeen() {
  try {
    return window.localStorage.getItem(SEEN_KEY);
  } catch {
    // Storage can be unavailable (private mode, disabled cookies). Treat
    // every event as fresh — the worst case is a duplicate toast.
    return null;
  }
}

function saveSeen(value) {
  try {
    window.localStorage.setItem(SEEN_KEY, value);
  } catch {
    // Ignore — see loadSeen comment.
  }
}

/**
 * Listens to /api/upscale/session-complete and fires a sticky sonner toast
 * once per session telling the founder to rescan Rekordbox.
 *
 * Dedup by ``session_completed_at`` in localStorage — if the SSE
 * reconnects after the event already fired (unlikely; the server closes
 * the stream after emitting once, but the founder may reload the tab
 * before clicking through), we don't show the toast again.
 */
export default function RekordboxRescanToast({ enabled = true }) {
  const onSessionComplete = useCallback((data) => {
    const replaced = Number(data?.replaced) || 0;
    if (replaced <= 0) return;
    const sessionKey = data?.session_completed_at || '';
    if (sessionKey && loadSeen() === sessionKey) return;
    if (sessionKey) saveSeen(sessionKey);

    const fileWord = replaced === 1 ? 'file' : 'files';
    toast.success(`Rekordbox rescan ready — ${replaced} ${fileWord} replaced.`, {
      duration: Infinity,
      description: 'Open Rekordbox and rescan your library to refresh cue points and beatgrids.',
      closeButton: true,
      id: `upscale-rescan-${sessionKey || 'noid'}`,
    });
  }, []);

  useUpscaleSessionStream({ enabled, onSessionComplete });
  return null;
}
