import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MatchResultPanel from './MatchResultPanel';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: { upscale: { search: vi.fn() } },
}));

const CAND = {
  id: 11,
  abs_path: '/m/song.mp3',
  bitrate_kbps: 128,
  size_bytes: 4000000,
  duration_s: 210,
  tag_title: 'Song',
  tag_artist: 'Artist',
  tag_album: '',
  last_scanned: null,
};

describe('MatchResultPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows a loading state then renders hits + tried list', async () => {
    let resolve;
    vi.mocked(api.upscale.search).mockImplementation(() => new Promise((r) => { resolve = r; }));
    render(<MatchResultPanel candidate={CAND} onClose={vi.fn()} />);
    expect(screen.getByText(/Querying DJ pools/i)).toBeInTheDocument();

    resolve({
      tried: [
        { slug: 'djcity', hits_count: 2, error: '' },
        { slug: 'zipdj', hits_count: 0, error: '' },
      ],
      served_by: 'djcity',
      hits: [
        { pool_slug: 'djcity', hit_id: 'a', title: 'Song (Extended Mix)', artist: 'Artist', bitrate_kbps: 320, format: 'MP3', duration_s: 215, preview_url: '', upscale_match_id: 1 },
        { pool_slug: 'djcity', hit_id: 'b', title: 'Song (Dirty)', artist: 'Artist', bitrate_kbps: 320, format: 'MP3', duration_s: 210, preview_url: '', upscale_match_id: 2 },
      ],
    });

    expect(await screen.findByText('Song (Extended Mix)')).toBeInTheDocument();
    expect(screen.getByText('Song (Dirty)')).toBeInTheDocument();
    expect(screen.getByText('djcity')).toBeInTheDocument();
    expect(screen.getByText('zipdj')).toBeInTheDocument();
    expect(screen.getAllByText('320 kbps').length).toBe(2);
  });

  it('renders an empty-state when zero hits', async () => {
    vi.mocked(api.upscale.search).mockResolvedValue({
      tried: [{ slug: 'djcity', hits_count: 0, error: '' }],
      served_by: '',
      hits: [],
    });
    render(<MatchResultPanel candidate={CAND} onClose={vi.fn()} />);
    expect(await screen.findByText(/No hits across the configured pools/)).toBeInTheDocument();
  });

  it('surfaces an error message on failure and supports Retry', async () => {
    vi.mocked(api.upscale.search)
      .mockRejectedValueOnce(new Error('all pools failed'))
      .mockResolvedValueOnce({
        tried: [{ slug: 'djcity', hits_count: 1, error: '' }],
        served_by: 'djcity',
        hits: [{
          pool_slug: 'djcity', hit_id: 'x', title: 'Recovered', artist: '',
          bitrate_kbps: 320, format: 'MP3', duration_s: null, preview_url: '', upscale_match_id: 9,
        }],
      });
    render(<MatchResultPanel candidate={CAND} onClose={vi.fn()} />);
    expect(await screen.findByText('all pools failed')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Retry'));
    expect(await screen.findByText('Recovered')).toBeInTheDocument();
  });

  it('calls onClose when the Close button is clicked', async () => {
    vi.mocked(api.upscale.search).mockResolvedValue({ tried: [], served_by: '', hits: [] });
    const onClose = vi.fn();
    render(<MatchResultPanel candidate={CAND} onClose={onClose} />);
    await waitFor(() => expect(api.upscale.search).toHaveBeenCalled());
    fireEvent.click(screen.getByRole('button', { name: /close search results/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
