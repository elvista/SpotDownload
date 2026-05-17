export default function UpscaleView() {
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold text-white tracking-tight">Upscale</h1>
        <p className="text-sm text-spotify-light-gray max-w-2xl leading-relaxed">
          Find low-bitrate tracks in your library and replace them with higher-quality
          versions from your DJ pool subscriptions — DJCity, zipDJ, and BPM Supreme — in
          place, preserving filename so Rekordbox cue points and beatgrids survive.
        </p>
      </header>

      <section
        aria-labelledby="upscale-pools-heading"
        className="rounded-xl border border-white/5 bg-spotify-dark-gray/60 p-6"
      >
        <h2
          id="upscale-pools-heading"
          className="text-xs uppercase tracking-wider text-spotify-light-gray/80 mb-3"
        >
          Pools
        </h2>
        <p className="text-sm text-spotify-light-gray">
          Pool status will appear here once connected. Backend is being wired up — this
          section will surface DJCity, zipDJ, and BPM Supreme connection state, plus the
          scan, search, replace, and history workflow.
        </p>
      </section>
    </div>
  );
}
