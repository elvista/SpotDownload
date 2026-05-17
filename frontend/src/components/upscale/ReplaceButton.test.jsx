import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ReplaceButton from './ReplaceButton';
import { api } from '../../api/client';

vi.mock('../../api/client', () => ({
  api: {
    upscale: {
      confirmMatch: vi.fn(),
      replaceMatch: vi.fn(),
    },
  },
}));

const MATCH = { id: 42, status: 'candidate', library_file_path: '/music/song.mp3' };

describe('ReplaceButton', () => {
  beforeEach(() => vi.clearAllMocks());

  it('arms on first click and fires confirm + replace on second click', async () => {
    vi.mocked(api.upscale.confirmMatch).mockResolvedValue({ id: 42, status: 'confirmed' });
    vi.mocked(api.upscale.replaceMatch).mockResolvedValue({ status: 'replaced', replace_log_id: 1 });
    const onReplaced = vi.fn();
    render(<ReplaceButton match={MATCH} onReplaced={onReplaced} />);
    fireEvent.click(screen.getByRole('button', { name: /Replace/ }));
    expect(await screen.findByRole('button', { name: /Tap again to overwrite/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Tap again to overwrite/i }));
    await waitFor(() => expect(api.upscale.confirmMatch).toHaveBeenCalledWith(42));
    await waitFor(() => expect(api.upscale.replaceMatch).toHaveBeenCalledWith(42));
    expect(await screen.findByText('Replaced')).toBeInTheDocument();
    expect(onReplaced).toHaveBeenCalledWith({ status: 'replaced', replace_log_id: 1 });
  });

  it('skips confirm step when match is already confirmed', async () => {
    vi.mocked(api.upscale.replaceMatch).mockResolvedValue({ status: 'replaced' });
    render(<ReplaceButton match={{ ...MATCH, status: 'confirmed' }} onReplaced={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Replace/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Tap again to overwrite/i }));
    await waitFor(() => expect(api.upscale.replaceMatch).toHaveBeenCalledWith(42));
    expect(api.upscale.confirmMatch).not.toHaveBeenCalled();
  });

  it('renders the BlockReasonsBanner on 409 with detail.kind="fingerprint_block"', async () => {
    vi.mocked(api.upscale.confirmMatch).mockResolvedValue({ id: 42, status: 'confirmed' });
    const blockErr = new Error('Fingerprint mismatch');
    blockErr.status = 409;
    blockErr.detail = {
      kind: 'fingerprint_block',
      message: 'Fingerprint mismatch',
      band: 'block',
      composite: 0.41,
      fingerprint: 0.22,
      reasons: ['title mismatch', 'duration off by 14s'],
    };
    vi.mocked(api.upscale.replaceMatch).mockRejectedValueOnce(blockErr);
    render(<ReplaceButton match={MATCH} onReplaced={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Replace/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Tap again to overwrite/i }));
    expect(await screen.findByText(/Swap blocked/i)).toBeInTheDocument();
    expect(screen.getByText(/title mismatch/)).toBeInTheDocument();
    expect(screen.getByText(/duration off by 14s/)).toBeInTheDocument();
  });

  it('shows a plain banner on other 409s (file locked, etc.)', async () => {
    vi.mocked(api.upscale.confirmMatch).mockResolvedValue({ id: 42, status: 'confirmed' });
    const lockErr = new Error('target file is locked — close it in any other app');
    lockErr.status = 409;
    lockErr.detail = 'target file is locked — close it in any other app';
    vi.mocked(api.upscale.replaceMatch).mockRejectedValueOnce(lockErr);
    render(<ReplaceButton match={MATCH} onReplaced={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Replace/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Tap again to overwrite/i }));
    expect(await screen.findByText(/target file is locked/i)).toBeInTheDocument();
    expect(screen.queryByText(/Swap blocked/i)).toBeNull();
  });

  it('surfaces a generic error on 5xx', async () => {
    vi.mocked(api.upscale.confirmMatch).mockResolvedValue({ id: 42, status: 'confirmed' });
    vi.mocked(api.upscale.replaceMatch).mockRejectedValueOnce(new Error('swap failed'));
    render(<ReplaceButton match={MATCH} onReplaced={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Replace/ }));
    fireEvent.click(await screen.findByRole('button', { name: /Tap again to overwrite/i }));
    expect(await screen.findByText('swap failed')).toBeInTheDocument();
  });
});
