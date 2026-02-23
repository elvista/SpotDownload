import { describe, it, expect, vi } from 'vitest';
import { render, screen, userEvent } from '@testing-library/react';
import TrackList from './TrackList';

const mockPlaylist = {
  id: 1,
  name: 'Test Playlist',
  description: 'Description',
  owner: 'Test User',
  image_url: '',
  track_count: 2,
  spotify_url: '',
  is_monitoring: true,
  tracks: [
    { id: 1, name: 'Track One', artist: 'Artist A', album: 'Album A', genre: '', duration_ms: 200000, is_new: true, is_downloaded: false, image_url: '', spotify_url: '' },
    { id: 2, name: 'Track Two', artist: 'Artist B', album: 'Album B', genre: 'Pop', duration_ms: 180000, is_new: false, is_downloaded: true, image_url: '', spotify_url: '' },
  ],
};

describe('TrackList', () => {
  it('returns null when playlist is null', () => {
    const { container } = render(
      <TrackList
        playlist={null}
        onDownload={vi.fn()}
        onDownloadAll={vi.fn()}
        onDownloadNew={vi.fn()}
        onRefresh={vi.fn()}
        downloadStatus={{}}
        refreshing={false}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders playlist name and track count', () => {
    render(
      <TrackList
        playlist={mockPlaylist}
        onDownload={vi.fn()}
        onDownloadAll={vi.fn()}
        onDownloadNew={vi.fn()}
        onRefresh={vi.fn()}
        downloadStatus={{}}
        refreshing={false}
      />
    );
    expect(screen.getByText('Test Playlist')).toBeInTheDocument();
    expect(screen.getByText(/2 songs/)).toBeInTheDocument();
    expect(screen.getByText(/1 downloaded/)).toBeInTheDocument();
    expect(screen.getByText(/1 new/)).toBeInTheDocument();
  });

  it('renders track names', () => {
    render(
      <TrackList
        playlist={mockPlaylist}
        onDownload={vi.fn()}
        onDownloadAll={vi.fn()}
        onDownloadNew={vi.fn()}
        onRefresh={vi.fn()}
        downloadStatus={{}}
        refreshing={false}
      />
    );
    expect(screen.getByText('Track One')).toBeInTheDocument();
    expect(screen.getByText('Track Two')).toBeInTheDocument();
  });

  it('calls onDownloadAll when Download All is clicked', async () => {
    const user = userEvent.setup();
    const onDownloadAll = vi.fn();
    render(
      <TrackList
        playlist={mockPlaylist}
        onDownload={vi.fn()}
        onDownloadAll={onDownloadAll}
        onDownloadNew={vi.fn()}
        onRefresh={vi.fn()}
        downloadStatus={{}}
        refreshing={false}
      />
    );
    await user.click(screen.getByRole('button', { name: /download all/i }));
    expect(onDownloadAll).toHaveBeenCalledTimes(1);
  });

  it('calls onRefresh when Check for Changes is clicked', async () => {
    const user = userEvent.setup();
    const onRefresh = vi.fn();
    render(
      <TrackList
        playlist={mockPlaylist}
        onDownload={vi.fn()}
        onDownloadAll={vi.fn()}
        onDownloadNew={vi.fn()}
        onRefresh={onRefresh}
        downloadStatus={{}}
        refreshing={false}
      />
    );
    await user.click(screen.getByRole('button', { name: /check for changes/i }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it('shows empty state when no tracks', () => {
    const emptyPlaylist = { ...mockPlaylist, tracks: [], track_count: 0 };
    render(
      <TrackList
        playlist={emptyPlaylist}
        onDownload={vi.fn()}
        onDownloadAll={vi.fn()}
        onDownloadNew={vi.fn()}
        onRefresh={vi.fn()}
        downloadStatus={{}}
        refreshing={false}
      />
    );
    expect(screen.getByText(/no tracks found/i)).toBeInTheDocument();
  });
});
