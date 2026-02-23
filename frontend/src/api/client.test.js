import { describe, it, expect, vi, beforeEach } from 'vitest';
import { api } from './client';

describe('api client', () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  it('getPlaylists returns data on 200', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: true,
      json: () => Promise.resolve([{ id: 1, name: 'Test' }]),
    });
    const result = await api.getPlaylists();
    expect(result).toEqual([{ id: 1, name: 'Test' }]);
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining('playlists'), expect.any(Object));
  });

  it('throws with message from detail on error response', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: () => Promise.resolve({ detail: 'Invalid playlist URL' }),
    });
    await expect(api.addPlaylist('bad')).rejects.toThrow('Invalid playlist URL');
  });

  it('throws generic message when response has no detail', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      json: () => Promise.reject(new Error('parse error')),
    });
    await expect(api.getPlaylists()).rejects.toThrow();
  });
});
