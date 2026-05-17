import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useUpscaleScanStream } from './useUpscaleScanStream';

// Minimal EventSource stub: holds onmessage/onerror handlers, exposes
// `emit()` so tests can fire SSE messages.
class StubEventSource {
  constructor(url) {
    this.url = url;
    this.closed = false;
    this.onmessage = null;
    this.onerror = null;
    StubEventSource.last = this;
  }
  emit(payload) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
  }
  fail() {
    if (this.onerror) this.onerror({});
  }
  close() {
    this.closed = true;
  }
}

describe('useUpscaleScanStream', () => {
  beforeEach(() => {
    StubEventSource.last = null;
    global.EventSource = StubEventSource;
  });
  afterEach(() => {
    delete global.EventSource;
  });

  it('starts idle when scanId is null', () => {
    const { result } = renderHook(() => useUpscaleScanStream(null));
    expect(result.current.phase).toBe('idle');
    expect(StubEventSource.last).toBeNull();
  });

  it('opens an EventSource for the given scan_id and transitions through start → progress → complete', () => {
    const { result } = renderHook(() => useUpscaleScanStream(42));
    expect(StubEventSource.last.url).toBe('/api/upscale/scan/42/stream');
    expect(result.current.phase).toBe('scanning');

    act(() => StubEventSource.last.emit({ type: 'start', root: '/m', total: 100 }));
    expect(result.current.total).toBe(100);
    expect(result.current.scanned).toBe(0);

    act(() => StubEventSource.last.emit({
      type: 'progress', scanned: 30, total: 100, candidates: 4, current: '/m/track.mp3',
    }));
    expect(result.current.scanned).toBe(30);
    expect(result.current.candidatesFound).toBe(4);
    expect(result.current.current).toBe('/m/track.mp3');

    act(() => StubEventSource.last.emit({
      type: 'complete', scanned: 100, candidates: 7, duration_s: 12.5,
    }));
    expect(result.current.phase).toBe('done');
    expect(result.current.scanned).toBe(100);
    expect(result.current.candidatesFound).toBe(7);
    expect(result.current.durationS).toBe(12.5);
    expect(StubEventSource.last.closed).toBe(true);
  });

  it('transitions to error on `error` event and closes the stream', () => {
    const { result } = renderHook(() => useUpscaleScanStream(7));
    act(() => StubEventSource.last.emit({ type: 'error', error: 'boom' }));
    expect(result.current.phase).toBe('error');
    expect(result.current.error).toBe('boom');
    expect(StubEventSource.last.closed).toBe(true);
  });

  it('treats a mid-scan transport drop as error', () => {
    const { result } = renderHook(() => useUpscaleScanStream(9));
    act(() => StubEventSource.last.fail());
    expect(result.current.phase).toBe('error');
    expect(StubEventSource.last.closed).toBe(true);
  });

  it('does NOT overwrite a terminal "done" phase if onerror fires after complete', () => {
    const { result } = renderHook(() => useUpscaleScanStream(11));
    act(() => StubEventSource.last.emit({
      type: 'complete', scanned: 5, candidates: 1, duration_s: 1,
    }));
    act(() => StubEventSource.last.fail());
    expect(result.current.phase).toBe('done');
  });

  it('closes the EventSource on unmount', () => {
    const { unmount } = renderHook(() => useUpscaleScanStream(3));
    const es = StubEventSource.last;
    unmount();
    expect(es.closed).toBe(true);
  });
});
