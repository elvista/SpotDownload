import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useAudioCoordinator } from './useAudioCoordinator';

// Stub HTMLAudioElement that supports addEventListener + a synthetic
// `dispatchPlay()` method for tests.
function makeAudio() {
  const listeners = {};
  return {
    paused: true,
    listeners,
    addEventListener(name, fn) {
      (listeners[name] = listeners[name] || []).push(fn);
    },
    removeEventListener(name, fn) {
      if (!listeners[name]) return;
      listeners[name] = listeners[name].filter((x) => x !== fn);
    },
    pause() { this.paused = true; },
    dispatchPlay() {
      this.paused = false;
      (listeners.play || []).forEach((fn) => fn({}));
    },
  };
}

describe('useAudioCoordinator', () => {
  it('pauses the other audio when one starts playing', () => {
    const { result } = renderHook(() => useAudioCoordinator());
    const a = makeAudio();
    const b = makeAudio();
    let aPauseCalls = 0;
    let bPauseCalls = 0;
    act(() => {
      result.current.register('a', a, () => { aPauseCalls += 1; });
      result.current.register('b', b, () => { bPauseCalls += 1; });
    });

    // Start `a`. b is already paused — no callback. Coordinator iterates but b.paused is true.
    act(() => a.dispatchPlay());
    expect(a.paused).toBe(false);
    expect(b.paused).toBe(true);
    expect(aPauseCalls).toBe(0);
    expect(bPauseCalls).toBe(0);

    // Now start `b`. Coordinator should pause `a` and fire its onPause.
    act(() => b.dispatchPlay());
    expect(a.paused).toBe(true);
    expect(b.paused).toBe(false);
    expect(aPauseCalls).toBe(1);
    expect(bPauseCalls).toBe(0);
  });

  it('unregister removes the listener', () => {
    const { result } = renderHook(() => useAudioCoordinator());
    const a = makeAudio();
    const b = makeAudio();
    let aPauseCalls = 0;
    let unregisterA;
    act(() => {
      unregisterA = result.current.register('a', a, () => { aPauseCalls += 1; });
      result.current.register('b', b, () => {});
    });
    act(() => { unregisterA(); });
    act(() => a.dispatchPlay()); // No listeners on `a` anymore → no broadcast.
    act(() => b.dispatchPlay()); // Should NOT pause `a` because it was unregistered.
    expect(aPauseCalls).toBe(0);
  });
});
