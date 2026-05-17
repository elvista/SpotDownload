import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useUpscaleSessionStream } from './useUpscaleSessionStream';

class StubEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    this.closed = false;
    StubEventSource.last = this;
  }
  addEventListener(name, fn) {
    (this.listeners[name] = this.listeners[name] || []).push(fn);
  }
  removeEventListener(name, fn) {
    if (!this.listeners[name]) return;
    this.listeners[name] = this.listeners[name].filter((x) => x !== fn);
  }
  emit(name, payload) {
    (this.listeners[name] || []).forEach((fn) => fn({ data: JSON.stringify(payload) }));
  }
  close() { this.closed = true; }
}

describe('useUpscaleSessionStream', () => {
  beforeEach(() => {
    StubEventSource.last = null;
    global.EventSource = StubEventSource;
  });
  afterEach(() => { delete global.EventSource; });

  it('opens /api/upscale/session-complete and registers the named event listener', () => {
    renderHook(() => useUpscaleSessionStream({ enabled: true, onSessionComplete: vi.fn() }));
    expect(StubEventSource.last.url).toBe('/api/upscale/session-complete');
    expect(StubEventSource.last.listeners.session_complete?.length).toBe(1);
  });

  it('does NOT open an EventSource when disabled', () => {
    renderHook(() => useUpscaleSessionStream({ enabled: false, onSessionComplete: vi.fn() }));
    expect(StubEventSource.last).toBeNull();
  });

  it('calls onSessionComplete with the parsed payload and closes the stream', () => {
    const cb = vi.fn();
    renderHook(() => useUpscaleSessionStream({ enabled: true, onSessionComplete: cb }));
    StubEventSource.last.emit('session_complete', {
      type: 'session_complete',
      replaced: 3,
      session_started_at: '2026-05-18T00:00:00Z',
      session_completed_at: '2026-05-18T00:00:05Z',
    });
    expect(cb).toHaveBeenCalledWith({
      type: 'session_complete',
      replaced: 3,
      session_started_at: '2026-05-18T00:00:00Z',
      session_completed_at: '2026-05-18T00:00:05Z',
    });
    expect(StubEventSource.last.closed).toBe(true);
  });

  it('reads the latest callback via ref (no effect re-run when callback changes)', () => {
    const a = vi.fn();
    const b = vi.fn();
    const { rerender } = renderHook(
      ({ cb }) => useUpscaleSessionStream({ enabled: true, onSessionComplete: cb }),
      { initialProps: { cb: a } },
    );
    const initialEs = StubEventSource.last;
    rerender({ cb: b });
    // Should NOT have opened a new EventSource just because the callback identity changed.
    expect(StubEventSource.last).toBe(initialEs);
    StubEventSource.last.emit('session_complete', { replaced: 1, session_completed_at: 't' });
    expect(a).not.toHaveBeenCalled();
    expect(b).toHaveBeenCalled();
  });

  it('closes the EventSource on unmount', () => {
    const { unmount } = renderHook(() => useUpscaleSessionStream({ enabled: true, onSessionComplete: vi.fn() }));
    const es = StubEventSource.last;
    unmount();
    expect(es.closed).toBe(true);
  });
});
