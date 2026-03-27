import React from 'react';
import { Link, NavLink } from 'react-router-dom';

export default React.memo(function Layout({
  children,
  onOpenSettings,
  onGoHome,
  showSettings = true,
}) {
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
                  <svg className="w-5 h-5 text-black" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.521 17.34c-.24.359-.66.48-1.021.24-2.82-1.74-6.36-2.101-10.561-1.141-.418.122-.779-.179-.899-.539-.12-.421.18-.78.54-.9 4.56-1.021 8.52-.6 11.64 1.32.42.18.479.659.301 1.02zm1.44-3.3c-.301.42-.841.6-1.262.3-3.239-1.98-8.159-2.58-11.939-1.38-.479.12-1.02-.12-1.14-.6-.12-.48.12-1.021.6-1.141C9.6 9.9 15 10.561 18.72 12.84c.361.181.54.78.241 1.2zm.12-3.36C15.24 8.4 8.82 8.16 5.16 9.301c-.6.179-1.2-.181-1.38-.721-.18-.601.18-1.2.72-1.381 4.26-1.26 11.28-1.02 15.721 1.621.539.3.719 1.02.419 1.56-.299.421-1.02.599-1.559.3z" />
                  </svg>
                </div>
                <div className="flex flex-col min-w-0">
                  <span className="text-xl font-bold text-white tracking-tight leading-tight">
                    Music <span className="text-spotify-green">Studio</span>
                  </span>
                  <span className="text-[10px] uppercase tracking-wider text-spotify-light-gray/80 hidden sm:block">
                    Spotify ID · mixtapes
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
              </nav>
            </div>

            <div className="flex items-center gap-4 ml-auto">
              <div className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-spotify-green pulse-green" />
                <span className="text-xs text-spotify-light-gray hidden sm:inline">Connected</span>
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
            Mixtape ID uses third-party fingerprinting APIs. Use of Spotify, YouTube, and those services is subject to
            their terms; respect applicable copyright.
          </p>
        </div>
      </footer>
    </div>
  );
});
