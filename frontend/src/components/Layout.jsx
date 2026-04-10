import React, { useEffect, useState } from 'react';
import { Link, NavLink } from 'react-router-dom';
import { api } from '../api/client';

export default React.memo(function Layout({
  children,
  onOpenSettings,
  onGoHome,
  showSettings = true,
}) {
  const [spotifyConnected, setSpotifyConnected] = useState(false);

  useEffect(() => {
    api.getAuthStatus().then((s) => setSpotifyConnected(s.connected)).catch(() => {});
    const interval = setInterval(() => {
      api.getAuthStatus().then((s) => setSpotifyConnected(s.connected)).catch(() => {});
    }, 15000);
    return () => clearInterval(interval);
  }, []);
  const navClass = ({ isActive }) =>
    `text-sm font-medium px-3 py-1.5 rounded-lg transition-colors ${
      isActive ? 'bg-white/10 text-white' : 'text-spotify-light-gray hover:text-white hover:bg-white/5'
    }`;

  return (
    <div className="min-h-screen bg-spotify-black flex flex-col">
      <header className="sticky top-0 z-50 bg-spotify-black/95 backdrop-blur-sm border-b border-white/5">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16 gap-4 flex-wrap">
            <div className="flex items-center gap-4 min-w-0">
              {onGoHome ? (
                <button
                  type="button"
                  onClick={onGoHome}
                  className="flex items-center gap-2 shrink-0 cursor-pointer hover:opacity-80 transition-opacity focus:outline-none focus:ring-2 focus:ring-spotify-green focus:ring-offset-2 focus:ring-offset-spotify-black rounded-lg text-sm text-spotify-light-gray hover:text-white"
                  aria-label="Back to Spotify ID"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                  Back
                </button>
              ) : null}

              <Link
                to="/"
                className="flex items-center gap-3 min-w-0 hover:opacity-90 transition-opacity focus:outline-none focus:ring-2 focus:ring-spotify-green focus:ring-offset-2 focus:ring-offset-spotify-black rounded-lg"
              >
                <div className="w-9 h-9 bg-spotify-green rounded-lg flex items-center justify-center shrink-0">
                  <svg className="w-6 h-6 text-black" fill="currentColor" viewBox="0 0 24 24">
                    {/* Vinyl record */}
                    <circle cx="12" cy="12" r="11" />
                    {/* Grooves */}
                    <circle cx="12" cy="12" r="8.5" fill="none" stroke="#F59E0B" strokeWidth="0.5" opacity="0.4" />
                    <circle cx="12" cy="12" r="6.5" fill="none" stroke="#F59E0B" strokeWidth="0.5" opacity="0.4" />
                    {/* Label */}
                    <circle cx="12" cy="12" r="4" fill="#F59E0B" />
                    {/* Spindle hole */}
                    <circle cx="12" cy="12" r="1.2" fill="black" />
                  </svg>
                </div>
                <div className="flex flex-col min-w-0">
                  <span className="text-xl font-bold text-white tracking-tight leading-tight">
                    Crate<span className="text-spotify-green">Digger</span>
                  </span>
                  <span className="text-[10px] uppercase tracking-wider text-spotify-light-gray/80 hidden sm:block">
                    Spotify ID · Mixtapes · Genre ID
                  </span>
                </div>
              </Link>

              <nav className="flex items-center gap-1 sm:gap-2" aria-label="Main">
                <NavLink to="/" end className={navClass}>
                  Spotify ID
                </NavLink>
                <NavLink to="/mixtape" className={navClass}>
                  Mixtape ID
                </NavLink>
                <NavLink to="/genreid" className={navClass}>
                  Genre ID
                </NavLink>
              </nav>
            </div>

            <div className="flex items-center gap-4 ml-auto">
              <div className="flex items-center gap-2">
                <div className={`h-2 w-2 rounded-full ${spotifyConnected ? 'bg-spotify-green pulse-green' : 'bg-red-400'}`} />
                <span className="text-xs text-spotify-light-gray hidden sm:inline">
                  {spotifyConnected ? 'Connected' : 'Disconnected'}
                </span>
              </div>
              {showSettings ? (
                <button
                  type="button"
                  onClick={onOpenSettings}
                  className="p-2 text-spotify-light-gray hover:text-white hover:bg-white/5 rounded-lg transition-all"
                  title="Settings"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
                    />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                  </svg>
                </button>
              ) : (
                <span className="w-10" aria-hidden />
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 flex-1 w-full">{children}</main>

      <footer className="border-t border-white/5 mt-auto py-6 px-4 sm:px-6 lg:px-8">
        <div className="max-w-7xl mx-auto">
          <p className="text-xs text-spotify-light-gray/90 leading-relaxed max-w-3xl">
            Spotify ID uses playlist and track metadata from Spotify; audio is matched via YouTube search (quality varies).
            Mixtape ID uses third-party fingerprinting APIs. Genre ID uses Claude AI to classify track genres.
            Use of Spotify, YouTube, and those services is subject to their terms; respect applicable copyright.
          </p>
        </div>
      </footer>
    </div>
  );
});
