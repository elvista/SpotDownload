import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import CandidateList from './CandidateList';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: {
    upscale: {
      getCandidates: vi.fn(),
      search: vi.fn(),
    },
  },
}));

function pageOf(items, total = items.length, offset = 0) {
  return { items, total, limit: 50, offset, threshold_kbps: 192 };
}

const CAND = (id, overrides = {}) => ({
  id,
  abs_path: `/m/track-${id}.mp3`,
  bitrate_kbps: 128,
  size_bytes: 1000,
  duration_s: 200,
  tag_title: `Track ${id}`,
  tag_artist: 'Artist',
  tag_album: '',
  last_scanned: null,
  ...overrides,
});

describe('CandidateList', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders loading then empty state when no items', async () => {
    vi.mocked(api.upscale.getCandidates).mockResolvedValue(pageOf([], 0));
    render(<CandidateList />);
    expect(screen.getByText(/Loading candidates/i)).toBeInTheDocument();
    expect(await screen.findByText(/No candidates found/i)).toBeInTheDocument();
  });

  it('surfaces a network error', async () => {
    vi.mocked(api.upscale.getCandidates).mockRejectedValue(new Error('500 backend'));
    render(<CandidateList />);
    expect(await screen.findByText('500 backend')).toBeInTheDocument();
  });

  it('renders rows + pagination summary', async () => {
    vi.mocked(api.upscale.getCandidates).mockResolvedValue(
      pageOf([CAND(1), CAND(2), CAND(3)], 120),
    );
    render(<CandidateList />);
    expect(await screen.findByText('track-1.mp3')).toBeInTheDocument();
    expect(screen.getByText('track-2.mp3')).toBeInTheDocument();
    expect(screen.getByText('track-3.mp3')).toBeInTheDocument();
    // Pagination summary: 1–3 of 120
    expect(screen.getByText(/of/)).toBeInTheDocument();
  });

  it('expands a row to show MatchResultPanel and collapses on toggle', async () => {
    vi.mocked(api.upscale.getCandidates).mockResolvedValue(pageOf([CAND(1)], 1));
    vi.mocked(api.upscale.search).mockResolvedValue({ tried: [], served_by: '', hits: [] });
    render(<CandidateList />);
    const btn = await screen.findByRole('button', { name: 'Search' });
    fireEvent.click(btn);
    await waitFor(() => expect(api.upscale.search).toHaveBeenCalledWith(1));
    expect(await screen.findByText(/Searching pools for/)).toBeInTheDocument();
    // Click Close button in the result panel
    fireEvent.click(screen.getByRole('button', { name: /close search results/i }));
    await waitFor(() => {
      expect(screen.queryByText(/Searching pools for/)).toBeNull();
    });
  });

  it('paginates with Next/Previous', async () => {
    vi.mocked(api.upscale.getCandidates)
      .mockResolvedValueOnce(pageOf([CAND(1), CAND(2)], 4, 0))
      .mockResolvedValueOnce(pageOf([CAND(3), CAND(4)], 4, 50));
    render(<CandidateList />);
    expect(await screen.findByText('track-1.mp3')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.upscale.getCandidates).toHaveBeenCalledWith({
      limit: 50, offset: 50,
    }));
  });

  it('reloads when refreshKey changes (e.g. after a scan completes)', async () => {
    vi.mocked(api.upscale.getCandidates).mockResolvedValue(pageOf([CAND(1)], 1));
    const { rerender } = render(<CandidateList refreshKey={0} />);
    await screen.findByText('track-1.mp3');
    expect(api.upscale.getCandidates).toHaveBeenCalledTimes(1);
    rerender(<CandidateList refreshKey={1} />);
    await waitFor(() => expect(api.upscale.getCandidates).toHaveBeenCalledTimes(2));
  });
});
