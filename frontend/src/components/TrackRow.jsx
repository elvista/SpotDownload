function formatDuration(ms) {
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.floor((ms % 60000) / 1000);
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
}

export default function TrackRow({ track, index, onDownload, downloadStatus }) {
  const status = downloadStatus?.[track.id];

  return (
    <tr className="group hover:bg-white/5 transition-colors">
      {/* Number */}
      <td className="py-3 px-4 text-sm text-spotify-light-gray w-12">
        {index + 1}
      </td>

      {/* Cover + Title + Artist */}
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
              <svg className="w-5 h-5 text-spotify-light-gray" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/>
              </svg>
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
                <svg className="flex-shrink-0 w-4 h-4 text-spotify-green" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                </svg>
              )}
            </div>
            <p className="text-xs text-spotify-light-gray truncate">{track.artist}</p>
          </div>
        </div>
      </td>

      {/* Album */}
      <td className="py-3 px-4 text-sm text-spotify-light-gray truncate max-w-[200px] hidden md:table-cell">
        {track.album}
      </td>

      {/* Duration */}
      <td className="py-3 px-4 text-sm text-spotify-light-gray w-20 hidden sm:table-cell">
        {formatDuration(track.duration_ms)}
      </td>

      {/* Download Button */}
      <td className="py-3 px-4 w-20">
        {status?.status === 'downloading' ? (
          <div className="flex items-center gap-2">
            <svg className="animate-spin w-4 h-4 text-spotify-green" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        ) : status?.status === 'completed' ? (
          <svg className="w-5 h-5 text-spotify-green" fill="currentColor" viewBox="0 0 24 24">
            <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
          </svg>
        ) : status?.status === 'failed' ? (
          <button
            onClick={() => onDownload([track.id])}
            className="text-red-400 hover:text-red-300 transition-colors"
            title="Retry download"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
          </button>
        ) : (
          <button
            onClick={() => onDownload([track.id])}
            className="opacity-0 group-hover:opacity-100 text-spotify-light-gray hover:text-spotify-green transition-all"
            title="Download track"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
          </button>
        )}
      </td>
    </tr>
  );
}
