import { useState } from 'react';

export default function PlaylistInput({ onSubmit, loading }) {
  const [url, setUrl] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (url.trim()) {
      onSubmit(url.trim());
    }
  };

  const isValidUrl = url.includes('spotify.com/playlist/') || url.includes('spotify:playlist:');

  return (
    <div className="animate-fade-in">
      <div className="mb-2">
        <h2 className="text-lg font-semibold text-white">Add Playlist</h2>
        <p className="text-sm text-spotify-light-gray mt-1">
          Paste a Spotify playlist URL to start tracking and downloading songs
        </p>
      </div>

      <form onSubmit={handleSubmit} className="flex gap-3 mt-4">
        <div className="relative flex-1">
          <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
            <svg className="w-5 h-5 text-spotify-light-gray" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" />
            </svg>
          </div>
          <input
            type="text"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://open.spotify.com/playlist/..."
            className="w-full pl-12 pr-4 py-3 bg-spotify-mid-gray border border-white/10 rounded-xl text-white placeholder-gray-500 focus:outline-none focus:border-spotify-green focus:ring-1 focus:ring-spotify-green transition-all"
          />
        </div>
        <button
          type="submit"
          disabled={!isValidUrl || loading}
          className="px-6 py-3 bg-spotify-green hover:bg-spotify-green-dark text-black font-semibold rounded-xl transition-all disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
        >
          {loading ? (
            <>
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Fetching...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              Add Playlist
            </>
          )}
        </button>
      </form>
    </div>
  );
}
