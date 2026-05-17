import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import ScanPanel from './ScanPanel';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: {
    upscale: {
      getSettings: vi.fn(),
      startScan: vi.fn(),
      listScans: vi.fn(),
    },
  },
}));

class StubEventSource {
  constructor() {
    this.onmessage = null;
    this.onerror = null;
    this.closed = false;
    StubEventSource.last = this;
  }
  emit(payload) {
    if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) });
  }
  close() { this.closed = true; }
}

describe('ScanPanel', () => {
  beforeEach(() => {
    StubEventSource.last = null;
    global.EventSource = StubEventSource;
    vi.mocked(api.upscale.getSettings).mockResolvedValue({ library_root: '/m', threshold_kbps: 192 });
    vi.mocked(api.upscale.listScans).mockResolvedValue([]);
  });
  afterEach(() => {
    delete global.EventSource;
    vi.clearAllMocks();
  });

  it('loads settings + last-scan on mount; Scan button is disabled until root is set', async () => {
    vi.mocked(api.upscale.getSettings).mockResolvedValueOnce({ library_root: '', threshold_kbps: 192 });
    render(<ScanPanel />);
    expect(await screen.findByText('Scan library')).toBeDisabled();
    expect(await screen.findByText(/Set a library root in Settings first/)).toBeInTheDocument();
  });

  it('shows progress when the SSE stream emits start + progress events', async () => {
    vi.mocked(api.upscale.startScan).mockResolvedValue({ scan_id: 7, root: '/m', threshold_kbps: 192 });
    render(<ScanPanel />);
    await screen.findByText('Scan library');
    fireEvent.click(screen.getByText('Scan library'));
    await waitFor(() => expect(api.upscale.startScan).toHaveBeenCalled());
    await waitFor(() => expect(StubEventSource.last).not.toBeNull());
    await act(async () => {
      StubEventSource.last.emit({ type: 'start', root: '/m', total: 200 });
      StubEventSource.last.emit({
        type: 'progress', scanned: 50, total: 200, candidates: 3, current: '/m/x.mp3',
      });
    });
    const bar = screen.getByRole('progressbar');
    expect(bar.getAttribute('aria-valuenow')).toBe('25');
  });

  it('renders the done banner after `complete` and notifies parent with candidate count', async () => {
    vi.mocked(api.upscale.startScan).mockResolvedValue({ scan_id: 9, root: '/m', threshold_kbps: 192 });
    const onComplete = vi.fn();
    render(<ScanPanel onScanComplete={onComplete} />);
    await screen.findByText('Scan library');
    fireEvent.click(screen.getByText('Scan library'));
    await waitFor(() => expect(StubEventSource.last).not.toBeNull());
    await act(async () => StubEventSource.last.emit({
      type: 'complete', scanned: 200, candidates: 12, duration_s: 8,
    }));
    expect(await screen.findByText(/Found/)).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
    await waitFor(() => expect(onComplete).toHaveBeenCalledWith({ scanId: 9, candidates: 12 }));
  });

  it('surfaces a scan error event', async () => {
    vi.mocked(api.upscale.startScan).mockResolvedValue({ scan_id: 5, root: '/m', threshold_kbps: 192 });
    render(<ScanPanel />);
    await screen.findByText('Scan library');
    fireEvent.click(screen.getByText('Scan library'));
    await waitFor(() => expect(StubEventSource.last).not.toBeNull());
    await act(async () => StubEventSource.last.emit({ type: 'error', error: 'permission denied' }));
    expect(await screen.findByText('permission denied')).toBeInTheDocument();
  });

  it('surfaces an HTTP error from /upscale/scan', async () => {
    vi.mocked(api.upscale.startScan).mockRejectedValueOnce(new Error('root does not exist'));
    render(<ScanPanel />);
    fireEvent.click(await screen.findByText('Scan library'));
    expect(await screen.findByText('root does not exist')).toBeInTheDocument();
  });
});
