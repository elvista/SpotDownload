const BASE_URL = '/api';

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: 'Request failed' }));
    const detail = error.detail;
    const message = typeof detail === 'string'
      ? detail
      : (detail && detail.message) || `HTTP ${res.status}`;
    const err = new Error(message);
    err.status = res.status;
    err.detail = detail;
    if (res.status === 409 && error.playlist) err.existingPlaylist = error.playlist;
    throw err;
  }

  return res.json();
}

export const api = {
  // Spotify playlists (Spotify ID)
  addPlaylist: (url) => request('/playlists', {
    method: 'POST',
    body: JSON.stringify({ url }),
  }),

  getPlaylists: () => request('/playlists'),

  getPlaylist: (id) => request(`/playlists/${id}`),

  deletePlaylist: (id) => request(`/playlists/${id}`, { method: 'DELETE' }),

  refreshPlaylist: (id) => request(`/playlists/${id}/refresh`, { method: 'POST' }),

  // Downloads
  downloadTracks: (trackIds) => request('/downloads', {
    method: 'POST',
    body: JSON.stringify({ track_ids: trackIds }),
  }),

  downloadPlaylist: (playlistId) => request('/downloads', {
    method: 'POST',
    body: JSON.stringify({ playlist_id: playlistId }),
  }),

  clearProgress: () => request('/downloads/progress', { method: 'DELETE' }),

  // Monitor
  checkAll: () => request('/monitor/check-all', { method: 'POST' }),

  checkPlaylist: (id) => request(`/monitor/check/${id}`, { method: 'POST' }),

  // Settings
  getSettings: () => request('/settings'),

  updateSettings: (data) => request('/settings', {
    method: 'PUT',
    body: JSON.stringify(data),
  }),

  validatePath: (path) => request('/settings/validate-path', {
    method: 'POST',
    body: JSON.stringify({ download_path: path }),
  }),

  // Auth
  getAuthStatus: () => request('/auth/spotify/status'),
  
  disconnectSpotify: () => request('/auth/spotify', { method: 'DELETE' }),

  // Genre ID
  getGenreIdDbStatus: () => request('/genreid/db-status'),

  setGenreIdDbPath: (path) => request('/genreid/db-path', {
    method: 'PUT',
    body: JSON.stringify({ path }),
  }),

  getGenreIdTracks: ({ search = '', page = 1, pageSize = 50, filter = 'all' } = {}) =>
    request(`/genreid/tracks?search=${encodeURIComponent(search)}&page=${page}&page_size=${pageSize}&filter=${filter}`),

  scanGenres: ({ rescan = false } = {}) => request('/genreid/scan', {
    method: 'POST',
    body: JSON.stringify({ rescan }),
  }),

  approveGenres: (tracks) => request('/genreid/approve', {
    method: 'POST',
    body: JSON.stringify({ tracks }),
  }),

  getStaged: () => request('/genreid/staged'),

  exportToLexicon: () => request('/genreid/export', { method: 'POST' }),

  clearStaged: () => request('/genreid/staged', { method: 'DELETE' }),

  // Upscale
  upscale: {
    getSettings: () => request('/upscale/settings'),
    updateSettings: ({ libraryRoot, thresholdKbps }) => request('/upscale/settings', {
      method: 'PUT',
      body: JSON.stringify({
        library_root: libraryRoot,
        threshold_kbps: thresholdKbps,
      }),
    }),

    getPools: () => request('/upscale/pools'),
    loginPool: (slug) => request(`/upscale/pools/${slug}/login`, { method: 'POST' }),
    clearPool: (slug) => request(`/upscale/pools/${slug}`, { method: 'DELETE' }),

    startScan: ({ root, thresholdKbps } = {}) => {
      const body = {};
      if (root !== undefined) body.root = root;
      if (thresholdKbps !== undefined) body.threshold_kbps = thresholdKbps;
      return request('/upscale/scan', {
        method: 'POST',
        body: JSON.stringify(body),
      });
    },
    getScan: (scanId) => request(`/upscale/scan/${scanId}`),
    listScans: ({ limit = 20 } = {}) => request(`/upscale/scans?limit=${limit}`),
    getCandidates: ({ limit = 50, offset = 0, thresholdKbps } = {}) => {
      const qs = new URLSearchParams({ limit, offset });
      if (thresholdKbps !== undefined) qs.set('threshold_kbps', thresholdKbps);
      return request(`/upscale/candidates?${qs}`);
    },

    search: (libraryFileId) => request('/upscale/search', {
      method: 'POST',
      body: JSON.stringify({ library_file_id: libraryFileId }),
    }),
    getMatch: (id) => request(`/upscale/match/${id}`),
    confirmMatch: (id) => request(`/upscale/match/${id}/confirm`, { method: 'POST' }),
    rejectMatch: (id) => request(`/upscale/match/${id}/reject`, { method: 'POST' }),
    previewUrl: (id) => `/api/upscale/match/${id}/preview`,
    previewOriginalUrl: (id) => `/api/upscale/match/${id}/preview-original`,

    replaceMatch: (matchId) => request(`/upscale/match/${matchId}/replace`, { method: 'POST' }),

    getReplaceLog: ({ limit = 50, offset = 0, libraryFileId } = {}) => {
      const qs = new URLSearchParams({ limit, offset });
      if (libraryFileId !== undefined) qs.set('library_file_id', libraryFileId);
      return request(`/upscale/replace-log?${qs}`);
    },
  },
};
