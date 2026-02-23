import React, { useCallback } from 'react';
import { formatDuration } from '../utils/format';
import { SpinnerIcon, CheckIcon, RefreshIcon, DownloadIcon, MusicIcon } from './Icons';

export default React.memo(function TrackRow({ track, index, onDownload, downloadStatus }) {
  const status = downloadStatus?.[track.id];

  const handleDownload = useCallback(() => {
    onDownload([track.id]);
  }, [onDownload, track.id]);

  return (
    <tr className={`group transition-colors ${!track.is_downloaded ? 'bg-spotify-green/10 hover:bg-spotify-green/15' : 'hover:bg-white/5'}`}>
      <td className="py-3 px-4 text-sm text-spotify-light-gray w-12">
        {index + 1}
      </td>

      <td className="py-3 px-4">
        <div className="flex items-center gap-3">
          {track.image_url ? (
            <img
              src={track.image_url}
              alt={track.name}
              className="w-10 h-10 rounded object-cover flex-shrink-0"
            />
          ) : (
            <div className="w-10 h-10 rounded bg-spotify-mid-gray flex items-center justify-center flex-shrink-0">
              <MusicIcon className="w-5 h-5 text-spotify-light-gray" />
            </div>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <p className="text-sm font-medium text-white truncate">
                {track.name}
              </p>
              {track.is_new && (
                <span className="flex-shrink-0 px-1.5 py-0.5 text-[10px] font-bold uppercase bg-spotify-green text-black rounded">
                  New
                </span>
              )}
              {track.is_downloaded && (
                <CheckIcon className="flex-shrink-0 w-4 h-4 text-spotify-green" />
              )}
            </div>
            <p className="text-xs text-spotify-light-gray truncate">{track.artist}</p>
          </div>
        </div>
      </td>

      <td className="py-3 px-4 text-sm text-spotify-light-gray truncate max-w-[200px] hidden md:table-cell">
        {track.album}
      </td>

      <td className="py-3 px-4 text-sm text-spotify-light-gray w-20 hidden sm:table-cell">
        {formatDuration(track.duration_ms)}
      </td>

      <td className="py-3 px-4 w-20">
        {status?.status === 'downloading' ? (
          <SpinnerIcon className="w-4 h-4 text-spotify-green" />
        ) : status?.status === 'completed' ? (
          <CheckIcon className="w-5 h-5 text-spotify-green" />
        ) : status?.status === 'failed' ? (
          <button onClick={handleDownload} className="text-red-400 hover:text-red-300 transition-colors" title="Retry download">
            <RefreshIcon className="w-5 h-5" />
          </button>
        ) : (
          <button onClick={handleDownload} className="opacity-0 group-hover:opacity-100 text-spotify-light-gray hover:text-spotify-green transition-all" title="Download track">
            <DownloadIcon className="w-5 h-5" />
          </button>
        )}
      </td>
    </tr>
  );
});
