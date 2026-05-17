import { useCallback, useEffect, useRef } from 'react';

/**
 * Coordinates a set of HTMLAudioElement instances so only one plays at a time.
 *
 * Each player registers itself with `register(id, element, onPause)`. When any
 * registered element starts playing, the coordinator pauses every other
 * registered element, preventing two preview clips from sounding at once
 * (echo, focus thrash, etc.).
 *
 * The hook returns a stable `register` function — call it from a `useEffect`
 * inside the player; the cleanup callback unregisters automatically.
 */
export function useAudioCoordinator() {
  const playersRef = useRef(new Map());

  const handlePlay = useCallback((winnerId) => {
    for (const [id, entry] of playersRef.current.entries()) {
      if (id !== winnerId && entry.element && !entry.element.paused) {
        try {
          entry.element.pause();
        } catch {
          // Ignore — autoplay/policy errors are not actionable here.
        }
        if (entry.onPause) entry.onPause();
      }
    }
  }, []);

  const register = useCallback((id, element, onPause) => {
    if (!element) return () => {};
    const onPlay = () => handlePlay(id);
    element.addEventListener('play', onPlay);
    playersRef.current.set(id, { element, onPause });
    return () => {
      element.removeEventListener('play', onPlay);
      playersRef.current.delete(id);
    };
  }, [handlePlay]);

  // On unmount, clear the registry so dangling references can be GC'd.
  useEffect(() => () => {
    playersRef.current.clear();
  }, []);

  return { register };
}
