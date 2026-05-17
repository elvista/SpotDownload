import { useCallback, useState } from 'react';
import ScanPanel from '../components/upscale/ScanPanel';
import CandidateList from '../components/upscale/CandidateList';
import ReplaceLogTable from '../components/upscale/ReplaceLogTable';

export default function UpscaleView() {
  const [candidatesRefreshKey, setCandidatesRefreshKey] = useState(0);
  const [logRefreshKey, setLogRefreshKey] = useState(0);

  const handleScanComplete = useCallback(() => {
    setCandidatesRefreshKey((k) => k + 1);
  }, []);

  // Each successful Replace shrinks the candidate set (the swapped file is now
  // above threshold) and appends a row to the Replace Log; refresh both.
  const handleReplaced = useCallback(() => {
    setCandidatesRefreshKey((k) => k + 1);
    setLogRefreshKey((k) => k + 1);
  }, []);

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

      <ScanPanel onScanComplete={handleScanComplete} />
      <CandidateList
        refreshKey={candidatesRefreshKey}
        onReplaced={handleReplaced}
      />
      <ReplaceLogTable refreshKey={logRefreshKey} />
    </div>
  );
}
