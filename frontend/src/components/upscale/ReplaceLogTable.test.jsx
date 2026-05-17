import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ReplaceLogTable from './ReplaceLogTable';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: { upscale: { getReplaceLog: vi.fn() } },
}));

const ROW = (id, overrides = {}) => ({
  id,
  library_file_id: 1,
  upscale_match_id: 7,
  abs_path: `/m/track-${id}.mp3`,
  archive_path: `/m/.upscale-archive/track-${id}.bak`,
  old_bitrate_kbps: 128,
  new_bitrate_kbps: 320,
  pool_slug: 'djcity',
  pool_source_url: 'https://djcity.com/x',
  file_size_before: 3 * 1024 * 1024,
  file_size_after: 7 * 1024 * 1024,
  id3_copy_status: 'ok',
  replaced_at: '2026-05-17T20:00:00Z',
  ...overrides,
});

function pageOf(items, total = items.length, offset = 0) {
  return { items, total, limit: 25, offset };
}

describe('ReplaceLogTable', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders empty state on zero rows', async () => {
    vi.mocked(api.upscale.getReplaceLog).mockResolvedValue(pageOf([], 0));
    render(<ReplaceLogTable />);
    expect(await screen.findByText(/No swaps yet/)).toBeInTheDocument();
  });

  it('surfaces a network error', async () => {
    vi.mocked(api.upscale.getReplaceLog).mockRejectedValue(new Error('502 upstream'));
    render(<ReplaceLogTable />);
    expect(await screen.findByText('502 upstream')).toBeInTheDocument();
  });

  it('renders rows with bitrate delta + pool + archive path', async () => {
    vi.mocked(api.upscale.getReplaceLog).mockResolvedValue(pageOf([ROW(1), ROW(2)]));
    const { container } = render(<ReplaceLogTable />);
    await screen.findAllByText('track-1.mp3');
    // Both the desktop table and the mobile card render the row, so we look
    // for the file basename and confirm at least one exists per row.
    expect(container.textContent).toContain('track-1.mp3');
    expect(container.textContent).toContain('track-2.mp3');
    expect(container.textContent).toContain('djcity');
    // Old/new bitrate shown as 128 → 320
    expect(container.textContent).toMatch(/128.*320/);
  });

  it('paginates with Next/Previous', async () => {
    vi.mocked(api.upscale.getReplaceLog)
      .mockResolvedValueOnce(pageOf([ROW(1)], 50, 0))
      .mockResolvedValueOnce(pageOf([ROW(2)], 50, 25));
    render(<ReplaceLogTable />);
    await screen.findAllByText('track-1.mp3');
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));
    await waitFor(() => expect(api.upscale.getReplaceLog).toHaveBeenLastCalledWith({
      limit: 25, offset: 25, libraryFileId: undefined,
    }));
  });

  it('reloads when refreshKey changes (after a Replace lands)', async () => {
    vi.mocked(api.upscale.getReplaceLog).mockResolvedValue(pageOf([ROW(1)]));
    const { rerender } = render(<ReplaceLogTable refreshKey={0} />);
    await screen.findAllByText('track-1.mp3');
    expect(api.upscale.getReplaceLog).toHaveBeenCalledTimes(1);
    rerender(<ReplaceLogTable refreshKey={1} />);
    await waitFor(() => expect(api.upscale.getReplaceLog).toHaveBeenCalledTimes(2));
  });
});
