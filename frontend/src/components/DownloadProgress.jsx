import React, { useMemo } from 'react';
import { SpinnerIcon, CheckIcon, ErrorIcon } from './Icons';

export default React.memo(function DownloadProgress({ downloads, onClear }) {
  const list = downloads ?? [];
  const { active, completed, failed } = useMemo(() => ({
    active: list.filter(d => d.status === 'downloading'),
    completed: list.filter(d => d.status === 'completed'),
    failed: list.filter(d => d.status === 'failed'),
  }), [downloads]);

  if (!downloads || downloads.length === 0) return null;

  return (
    <div className="fixed bottom-0 left-0 right-0 z-40 bg-spotify-dark-gray border-t border-white/10 shadow-2xl animate-fade-in">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-4">
            <h3 className="text-sm font-semibold text-white">Downloads</h3>
            <div className="flex items-center gap-3 text-xs">
              {active.length > 0 && (
                <span className="text-spotify-green flex items-center gap-1">
                  <SpinnerIcon className="w-3 h-3" /> {active.length} downloading
                </span>
              )}
              {completed.length > 0 && (
                <span className="text-spotify-green">{completed.length} completed</span>
              )}
              {failed.length > 0 && (
                <span className="text-red-400">{failed.length} failed</span>
              )}
            </div>
          </div>
          <button onClick={onClear} className="text-xs text-spotify-light-gray hover:text-white transition-colors">
            Clear
          </button>
        </div>
        <div className="max-h-40 overflow-y-auto space-y-2">
          {downloads.map((dl) => (
            <div key={dl.id} className="flex items-center gap-3">
              {dl.status === 'downloading' && <SpinnerIcon className="w-4 h-4 text-spotify-green flex-shrink-0" />}
              {dl.status === 'completed' && <CheckIcon className="w-4 h-4 text-spotify-green flex-shrink-0" />}
              {dl.status === 'failed' && <ErrorIcon className="w-4 h-4 text-red-400 flex-shrink-0" />}
              <div className="min-w-0 flex-1">
                <p className="text-sm text-white truncate">{dl.name}</p>
                <p className="text-xs text-spotify-light-gray truncate">{dl.artist}</p>
              </div>
              <span className={`text-xs font-medium ${dl.status === 'failed' ? 'text-red-400' : 'text-spotify-green'}`}>
                {dl.status === 'downloading' ? 'Downloading...' : dl.status === 'completed' ? 'Done' : 'Failed'}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});
