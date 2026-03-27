import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, userEvent } from '@testing-library/react';
import SettingsModal from './SettingsModal';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getSettings: vi.fn(),
    getAuthStatus: vi.fn(),
    updateSettings: vi.fn(),
    validatePath: vi.fn(),
    disconnectSpotify: vi.fn(),
  },
}));

describe('SettingsModal', () => {
  beforeEach(() => {
    vi.mocked(api.getSettings).mockResolvedValue({
      download_path: '/tmp/music',
      monitor_interval_minutes: 30,
      archive_playlist_name: 'DJ Archive',
    });
    vi.mocked(api.getAuthStatus).mockResolvedValue({
      connected: false,
      redirect_uri: 'http://127.0.0.1:8000/api/auth/spotify/callback',
      redirect_uri_warnings: [],
    });
    vi.clearAllMocks();
  });

  it('renders nothing when not open', () => {
    const { container } = render(<SettingsModal isOpen={false} onClose={vi.fn()} />);
    expect(container.querySelector('[role="dialog"]')).not.toBeInTheDocument();
  });

  it('loads and displays settings when opened', async () => {
    render(<SettingsModal isOpen={true} onClose={vi.fn()} />);
    expect(api.getSettings).toHaveBeenCalled();
    expect(api.getAuthStatus).toHaveBeenCalled();
    await screen.findByDisplayValue('/tmp/music');
    expect(screen.getByDisplayValue('30')).toBeInTheDocument();
    expect(screen.getByDisplayValue('DJ Archive')).toBeInTheDocument();
  });

  it('calls onClose when close button is clicked', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<SettingsModal isOpen={true} onClose={onClose} />);
    await screen.findByDisplayValue('/tmp/music');
    const closeButton = screen.getByRole('button', { name: /close/i });
    await user.click(closeButton);
    expect(onClose).toHaveBeenCalled();
  });

  it('calls updateSettings when Save is clicked', async () => {
    const user = userEvent.setup();
    vi.mocked(api.updateSettings).mockResolvedValue({});
    render(<SettingsModal isOpen={true} onClose={vi.fn()} />);
    const archiveInput = await screen.findByDisplayValue('DJ Archive');
    await user.clear(archiveInput);
    await user.type(archiveInput, 'My Archive');
    await user.click(screen.getByRole('button', { name: /save settings/i }));
    expect(api.updateSettings).toHaveBeenCalledWith(
      expect.objectContaining({ archive_playlist_name: 'My Archive' })
    );
  });
});
