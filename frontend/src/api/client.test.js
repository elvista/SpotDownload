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

  it('surfaces err.status and err.detail on error responses', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: () => Promise.resolve({ detail: 'invalid bitrate' }),
    });
    try {
      await api.getPlaylists();
      throw new Error('should not reach');
    } catch (e) {
      expect(e.status).toBe(422);
      expect(e.detail).toBe('invalid bitrate');
      expect(e.message).toBe('invalid bitrate');
    }
  });

  it('passes structured detail through on 409 block responses', async () => {
    global.fetch.mockResolvedValueOnce({
      ok: false,
      status: 409,
      json: () => Promise.resolve({
        detail: {
          kind: 'fingerprint_block',
          message: 'Fingerprint mismatch',
          band: 'block',
          composite: 0.41,
          fingerprint: 0.22,
          reasons: ['title mismatch', 'duration off by 14s'],
        },
      }),
    });
    try {
      await api.upscale.replace(42);
      throw new Error('should not reach');
    } catch (e) {
      expect(e.status).toBe(409);
      expect(e.message).toBe('Fingerprint mismatch');
      expect(e.detail.kind).toBe('fingerprint_block');
      expect(e.detail.band).toBe('block');
      expect(e.detail.reasons).toEqual(['title mismatch', 'duration off by 14s']);
    }
  });

  describe('api.upscale', () => {
    it('getPools hits /upscale/pools', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([{ slug: 'djcity', connected: false }]),
      });
      const result = await api.upscale.getPools();
      expect(result).toEqual([{ slug: 'djcity', connected: false }]);
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/upscale/pools'),
        expect.any(Object),
      );
    });

    it('loginPool POSTs to the slug-scoped login route', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
      await api.upscale.loginPool('zipdj');
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/upscale/pools/zipdj/login'),
        expect.objectContaining({ method: 'POST' }),
      );
    });

    it('search posts library_file_id', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ hits: [] }) });
      await api.upscale.search(17);
      const [, opts] = global.fetch.mock.calls[0];
      expect(opts.method).toBe('POST');
      expect(JSON.parse(opts.body)).toEqual({ library_file_id: 17 });
    });

    it('replace posts match_id', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ ok: true }) });
      await api.upscale.replace(99);
      const [, opts] = global.fetch.mock.calls[0];
      expect(opts.method).toBe('POST');
      expect(JSON.parse(opts.body)).toEqual({ match_id: 99 });
    });

    it('previewUrl returns the streaming endpoint for <audio src>', () => {
      expect(api.upscale.previewUrl(3)).toBe('/api/upscale/match/3/preview');
    });

    it('getReplaceLog passes filters as query params', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve([]) });
      await api.upscale.getReplaceLog({
        page: 2,
        pageSize: 25,
        from: '2026-01-01',
        pool: 'bpm',
      });
      const [url] = global.fetch.mock.calls[0];
      expect(url).toContain('page=2');
      expect(url).toContain('page_size=25');
      expect(url).toContain('from=2026-01-01');
      expect(url).toContain('pool=bpm');
    });
  });
});
