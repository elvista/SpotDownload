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
    const err = new Error(error.detail || `HTTP ${res.status}`);
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
};
