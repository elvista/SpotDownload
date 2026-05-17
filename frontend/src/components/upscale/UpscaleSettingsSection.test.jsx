import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import UpscaleSettingsSection from './UpscaleSettingsSection';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: {
    upscale: {
      getSettings: vi.fn(),
      updateSettings: vi.fn(),
      getPools: vi.fn(),
      loginPool: vi.fn(),
      clearPool: vi.fn(),
    },
  },
}));

const POOL_DJCITY_DISCONNECTED = {
  slug: 'djcity',
  display_name: 'DJCity',
  connected: false,
  last_login: null,
  last_error: '',
  enabled: true,
};

const POOL_DJCITY_CONNECTED = {
  ...POOL_DJCITY_DISCONNECTED,
  connected: true,
  last_login: new Date(Date.now() - 60_000).toISOString(),
};

describe('UpscaleSettingsSection', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(api.upscale.getSettings).mockResolvedValue({
      library_root: '/music',
      threshold_kbps: 192,
    });
    vi.mocked(api.upscale.getPools).mockResolvedValue([POOL_DJCITY_DISCONNECTED]);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('renders nothing when modal is closed', () => {
    render(<UpscaleSettingsSection isOpen={false} />);
    expect(api.upscale.getSettings).not.toHaveBeenCalled();
    expect(api.upscale.getPools).not.toHaveBeenCalled();
  });

  it('loads settings + pools and renders the form when open', async () => {
    render(<UpscaleSettingsSection isOpen />);
    await waitFor(() => expect(api.upscale.getSettings).toHaveBeenCalled());
    await waitFor(() => expect(api.upscale.getPools).toHaveBeenCalled());
    expect(await screen.findByDisplayValue('/music')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('192')).toBeInTheDocument();
    expect(await screen.findByText('DJCity')).toBeInTheDocument();
    expect(await screen.findByRole('button', { name: 'Connect DJCity' })).toBeEnabled();
  });

  it('shows the feature-flag-off banner when pools report enabled: false', async () => {
    vi.mocked(api.upscale.getPools).mockResolvedValueOnce([
      { ...POOL_DJCITY_DISCONNECTED, enabled: false },
    ]);
    render(<UpscaleSettingsSection isOpen />);
    expect(await screen.findByText('DJCity')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect DJCity' })).toBeDisabled();
  });

  it('saves upscale settings on Save click and surfaces "Saved"', async () => {
    vi.mocked(api.upscale.updateSettings).mockResolvedValue({
      library_root: '/music/new',
      threshold_kbps: 224,
    });
    render(<UpscaleSettingsSection isOpen />);
    await screen.findByDisplayValue('/music');
    fireEvent.change(screen.getByLabelText('Library root'), {
      target: { value: '/music/new' },
    });
    fireEvent.change(screen.getByLabelText('Bitrate threshold'), {
      target: { value: '224' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save upscale/i }));
    await waitFor(() => {
      expect(api.upscale.updateSettings).toHaveBeenCalledWith({
        libraryRoot: '/music/new',
        thresholdKbps: 224,
      });
    });
    expect(await screen.findByText('Saved')).toBeInTheDocument();
  });

  it('starts a login poll and reports success when the pool connects', async () => {
    vi.mocked(api.upscale.loginPool).mockResolvedValue({ slug: 'djcity', status: 'started', message: 'ok' });
    // First getPools call (mount) returns disconnected. After Connect click,
    // poll(s) eventually flip to connected.
    vi.mocked(api.upscale.getPools)
      .mockResolvedValueOnce([POOL_DJCITY_DISCONNECTED]) // mount
      .mockResolvedValueOnce([POOL_DJCITY_DISCONNECTED]) // first poll
      .mockResolvedValue([POOL_DJCITY_CONNECTED]); // subsequent polls
    render(<UpscaleSettingsSection isOpen />);
    const btn = await screen.findByRole('button', { name: 'Connect DJCity' });
    fireEvent.click(btn);
    await waitFor(() => expect(api.upscale.loginPool).toHaveBeenCalledWith('djcity'));
    expect(await screen.findByText(/browser window opened/i)).toBeInTheDocument();
    // Advance polling clock.
    await vi.advanceTimersByTimeAsync(3000);
    await vi.advanceTimersByTimeAsync(3000);
    expect(await screen.findByText('DJCity connected.')).toBeInTheDocument();
  });

  it('surfaces a 503 error when pool scraping is disabled at backend', async () => {
    const err = new Error('Pool scraping is disabled');
    err.status = 503;
    vi.mocked(api.upscale.loginPool).mockRejectedValueOnce(err);
    render(<UpscaleSettingsSection isOpen />);
    fireEvent.click(await screen.findByRole('button', { name: 'Connect DJCity' }));
    expect(await screen.findByText(/UPSCALE_POOLS_ENABLED=1/)).toBeInTheDocument();
  });

  it('disconnects a connected pool', async () => {
    vi.mocked(api.upscale.getPools)
      .mockResolvedValueOnce([POOL_DJCITY_CONNECTED])
      .mockResolvedValueOnce([POOL_DJCITY_DISCONNECTED]); // after clear
    vi.mocked(api.upscale.clearPool).mockResolvedValue({});
    render(<UpscaleSettingsSection isOpen />);
    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect DJCity' }));
    await waitFor(() => expect(api.upscale.clearPool).toHaveBeenCalledWith('djcity'));
    expect(await screen.findByText(/djcity session cleared/i)).toBeInTheDocument();
  });
});
