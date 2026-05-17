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
      await api.upscale.replaceMatch(42);
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

    it('getSettings hits /upscale/settings', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ library_root: '/music', threshold_kbps: 192 }),
      });
      const result = await api.upscale.getSettings();
      expect(result).toEqual({ library_root: '/music', threshold_kbps: 192 });
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining('/upscale/settings'),
        expect.any(Object),
      );
    });

    it('updateSettings PUTs snake_case payload', async () => {
      global.fetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ library_root: '/library', threshold_kbps: 256 }),
      });
      await api.upscale.updateSettings({ libraryRoot: '/library', thresholdKbps: 256 });
      const [, opts] = global.fetch.mock.calls[0];
      expect(opts.method).toBe('PUT');
      expect(JSON.parse(opts.body)).toEqual({ library_root: '/library', threshold_kbps: 256 });
    });

    it('replaceMatch POSTs to /upscale/match/:id/replace', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
      await api.upscale.replaceMatch(42);
      const [url, opts] = global.fetch.mock.calls[0];
      expect(url).toContain('/upscale/match/42/replace');
      expect(opts.method).toBe('POST');
    });

    it('confirmMatch + getMatch hit the right endpoints', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
      await api.upscale.confirmMatch(7);
      expect(global.fetch.mock.calls[0][0]).toContain('/upscale/match/7/confirm');
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
      await api.upscale.getMatch(7);
      expect(global.fetch.mock.calls[1][0]).toContain('/upscale/match/7');
    });

    it('getReplaceLog uses limit + offset and optional library_file_id', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ items: [], total: 0 }) });
      await api.upscale.getReplaceLog({ limit: 25, offset: 50, libraryFileId: 11 });
      const url = global.fetch.mock.calls[0][0];
      expect(url).toContain('limit=25');
      expect(url).toContain('offset=50');
      expect(url).toContain('library_file_id=11');
    });

    it('previewOriginalUrl + previewUrl return streaming endpoints', () => {
      expect(api.upscale.previewUrl(3)).toBe('/api/upscale/match/3/preview');
      expect(api.upscale.previewOriginalUrl(3)).toBe('/api/upscale/match/3/preview-original');
    });

    it('clearPool DELETEs the slug-scoped endpoint', async () => {
      global.fetch.mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({}) });
      await api.upscale.clearPool('djcity');
      const [url, opts] = global.fetch.mock.calls[0];
      expect(url).toContain('/upscale/pools/djcity');
      expect(opts.method).toBe('DELETE');
    });

  });
});
