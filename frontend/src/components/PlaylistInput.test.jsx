import { describe, it, expect, vi } from 'vitest';
import { render, screen, userEvent } from '@testing-library/react';
import PlaylistInput from './PlaylistInput';

describe('PlaylistInput', () => {
  it('renders input and add button', () => {
    render(<PlaylistInput onSubmit={() => {}} loading={false} />);
    expect(screen.getByPlaceholderText(/spotify\.com\/playlist/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add playlist/i })).toBeInTheDocument();
  });

  it('disables submit when URL is invalid', async () => {
    const user = userEvent.setup();
    render(<PlaylistInput onSubmit={() => {}} loading={false} />);
    const input = screen.getByPlaceholderText(/spotify\.com\/playlist/);
    const button = screen.getByRole('button', { name: /add playlist/i });
    expect(button).toBeDisabled();
    await user.type(input, 'https://example.com');
    expect(button).toBeDisabled();
  });

  it('enables submit when URL contains spotify playlist', async () => {
    const user = userEvent.setup();
    render(<PlaylistInput onSubmit={() => {}} loading={false} />);
    const input = screen.getByPlaceholderText(/spotify\.com\/playlist/);
    await user.type(input, 'https://open.spotify.com/playlist/abc123');
    expect(screen.getByRole('button', { name: /add playlist/i })).not.toBeDisabled();
  });

  it('calls onSubmit with trimmed URL on submit', async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(<PlaylistInput onSubmit={onSubmit} loading={false} />);
    const input = screen.getByPlaceholderText(/spotify\.com\/playlist/);
    await user.type(input, '  https://open.spotify.com/playlist/xyz  ');
    await user.click(screen.getByRole('button', { name: /add playlist/i }));
    expect(onSubmit).toHaveBeenCalledWith('https://open.spotify.com/playlist/xyz');
  });

  it('shows loading state and disables button when loading', () => {
    render(<PlaylistInput onSubmit={() => {}} loading={true} />);
    expect(screen.getByText(/fetching/i)).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeDisabled();
  });
});
