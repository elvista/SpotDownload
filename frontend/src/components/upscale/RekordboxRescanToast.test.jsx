import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render } from '@testing-library/react';
import RekordboxRescanToast from './RekordboxRescanToast';
import { toast } from 'sonner';

vi.mock('sonner', () => ({
  toast: { success: vi.fn() },
}));

class StubEventSource {
  constructor(url) {
    this.url = url;
    this.listeners = {};
    StubEventSource.last = this;
  }
  addEventListener(name, fn) {
    (this.listeners[name] = this.listeners[name] || []).push(fn);
  }
  removeEventListener() {}
  emit(name, payload) {
    (this.listeners[name] || []).forEach((fn) => fn({ data: JSON.stringify(payload) }));
  }
  close() {}
}

describe('RekordboxRescanToast', () => {
  beforeEach(() => {
    StubEventSource.last = null;
    global.EventSource = StubEventSource;
    window.localStorage.clear();
    vi.mocked(toast.success).mockClear();
  });
  afterEach(() => { delete global.EventSource; });

  it('fires the toast once when the SSE emits a session_complete event with replaced > 0', () => {
    render(<RekordboxRescanToast />);
    StubEventSource.last.emit('session_complete', {
      replaced: 3,
      session_completed_at: '2026-05-18T01:00:00Z',
    });
    expect(toast.success).toHaveBeenCalledWith(
      'Rekordbox rescan ready — 3 files replaced.',
      expect.objectContaining({ duration: Infinity, closeButton: true }),
    );
  });

  it('uses singular "file" when replaced === 1', () => {
    render(<RekordboxRescanToast />);
    StubEventSource.last.emit('session_complete', {
      replaced: 1,
      session_completed_at: '2026-05-18T02:00:00Z',
    });
    expect(toast.success).toHaveBeenCalledWith(
      'Rekordbox rescan ready — 1 file replaced.',
      expect.any(Object),
    );
  });

  it('does NOT fire the toast when replaced is 0', () => {
    render(<RekordboxRescanToast />);
    StubEventSource.last.emit('session_complete', {
      replaced: 0,
      session_completed_at: '2026-05-18T03:00:00Z',
    });
    expect(toast.success).not.toHaveBeenCalled();
  });

  it('dedupes via localStorage so the same session does not re-fire on remount', () => {
    const payload = { replaced: 2, session_completed_at: '2026-05-18T04:00:00Z' };
    const { unmount } = render(<RekordboxRescanToast />);
    StubEventSource.last.emit('session_complete', payload);
    expect(toast.success).toHaveBeenCalledTimes(1);
    unmount();
    // Re-mount and re-emit the same session — should be deduped.
    render(<RekordboxRescanToast />);
    StubEventSource.last.emit('session_complete', payload);
    expect(toast.success).toHaveBeenCalledTimes(1);
  });

  it('does NOT open an EventSource when enabled=false', () => {
    render(<RekordboxRescanToast enabled={false} />);
    expect(StubEventSource.last).toBeNull();
  });
});
