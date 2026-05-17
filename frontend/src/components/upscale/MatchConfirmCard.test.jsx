import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import MatchConfirmCard from './MatchConfirmCard';
import { api } from '../../api/client';

vi.mock('../../api/client', async () => {
  const real = await vi.importActual('../../api/client');
  return {
    api: {
      upscale: {
        confirmMatch: vi.fn(),
        rejectMatch: vi.fn(),
        replaceMatch: vi.fn(),
        previewUrl: real.api.upscale.previewUrl,
        previewOriginalUrl: real.api.upscale.previewOriginalUrl,
      },
    },
  };
});

const HIT = {
  upscale_match_id: 7,
  pool_slug: 'djcity',
  title: 'Song (Extended Mix)',
  artist: 'Artist',
  bitrate_kbps: 320,
  format: 'MP3',
  duration_s: 210,
  preview_url: 'https://x/p',
};

const CAND = { id: 1, abs_path: '/m/song.mp3' };

describe('MatchConfirmCard', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders metadata + an A/B audio region', () => {
    render(<MatchConfirmCard hit={HIT} candidate={CAND} onClose={vi.fn()} />);
    expect(screen.getByText(/Song \(Extended Mix\)/)).toBeInTheDocument();
    expect(screen.getByText('Artist')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: /A\/B audio preview/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Play Current/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Play Pool hit/i })).toBeInTheDocument();
  });

  it('Confirm flips status; Replace becomes enabled afterwards', async () => {
    vi.mocked(api.upscale.confirmMatch).mockResolvedValue({ id: 7, status: 'confirmed' });
    render(<MatchConfirmCard hit={HIT} candidate={CAND} onClose={vi.fn()} />);
    // Pre-confirm: Replace button exists but is disabled.
    const replaceBtn = screen.getByRole('button', { name: 'Replace' });
    expect(replaceBtn).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: /Confirm match/ }));
    await waitFor(() => expect(api.upscale.confirmMatch).toHaveBeenCalledWith(7));
    expect(await screen.findByRole('button', { name: /Confirmed/ })).toBeInTheDocument();
    // Replace should be enabled now.
    await waitFor(() => expect(screen.getByRole('button', { name: 'Replace' })).not.toBeDisabled());
  });

  it('Reject flips status to rejected, locking Confirm/Reject and leaving Replace disabled', async () => {
    vi.mocked(api.upscale.rejectMatch).mockResolvedValue({ id: 7, status: 'rejected' });
    render(<MatchConfirmCard hit={HIT} candidate={CAND} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Reject' }));
    await waitFor(() => expect(api.upscale.rejectMatch).toHaveBeenCalledWith(7));
    expect(await screen.findByRole('button', { name: 'Rejected' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Replace' })).toBeDisabled();
  });

  it('surfaces an HTTP error from confirm', async () => {
    vi.mocked(api.upscale.confirmMatch).mockRejectedValue(new Error('match not found'));
    render(<MatchConfirmCard hit={HIT} candidate={CAND} onClose={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Confirm match/ }));
    expect(await screen.findByText('match not found')).toBeInTheDocument();
  });

  it('Close button triggers onClose', () => {
    const onClose = vi.fn();
    render(<MatchConfirmCard hit={HIT} candidate={CAND} onClose={onClose} />);
    fireEvent.click(screen.getByRole('button', { name: /Close preview/i }));
    expect(onClose).toHaveBeenCalled();
  });
});
