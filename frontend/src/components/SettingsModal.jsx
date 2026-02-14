import { useState, useEffect } from 'react';
import { api } from '../api/client';

export default function SettingsModal({ isOpen, onClose }) {
  const [downloadPath, setDownloadPath] = useState('');
  const [monitorInterval, setMonitorInterval] = useState(30);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);
  const [pathStatus, setPathStatus] = useState(null);

  useEffect(() => {
    if (isOpen) {
      loadSettings();
    }
  }, [isOpen]);

  const loadSettings = async () => {
    try {
      const data = await api.getSettings();
      setDownloadPath(data.download_path);
      setMonitorInterval(data.monitor_interval_minutes);
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await api.updateSettings({
        download_path: downloadPath,
        monitor_interval_minutes: monitorInterval,
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const handleValidatePath = async () => {
    setPathStatus(null);
    try {
      const result = await api.validatePath(downloadPath);
      setPathStatus(result);
      // Update the input with the resolved path
      setDownloadPath(result.path);
    } catch (err) {
      setError(err.message);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-spotify-dark-gray rounded-2xl shadow-2xl w-full max-w-lg mx-4 animate-fade-in">
        {/* Header */}
        <div className="flex items-center justify-between p-6 border-b border-white/5">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 bg-spotify-mid-gray rounded-lg flex items-center justify-center">
              <svg className="w-4 h-4 text-spotify-light-gray" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
            </div>
            <h2 className="text-lg font-semibold text-white">Settings</h2>
          </div>
          <button
            onClick={onClose}
            className="text-spotify-light-gray hover:text-white transition-colors p-1"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div className="p-6 space-y-6">
          {/* Download Path */}
          <div>
            <label className="block text-sm font-medium text-white mb-2">
              Download Location
            </label>
            <p className="text-xs text-spotify-light-gray mb-3">
              Where downloaded MP3 files will be saved on your computer
            </p>
            <div className="flex gap-2">
              <input
                type="text"
                value={downloadPath}
                onChange={(e) => {
                  setDownloadPath(e.target.value);
                  setPathStatus(null);
                }}
                placeholder="/Users/you/Music/SpotDownload"
                className="flex-1 px-4 py-2.5 bg-spotify-mid-gray border border-white/10 rounded-xl text-white text-sm placeholder-gray-500 focus:outline-none focus:border-spotify-green focus:ring-1 focus:ring-spotify-green transition-all font-mono"
              />
              <button
                onClick={handleValidatePath}
                className="px-4 py-2.5 bg-spotify-mid-gray hover:bg-white/10 text-spotify-light-gray hover:text-white text-sm rounded-xl transition-all whitespace-nowrap border border-white/10"
                title="Validate path"
              >
                Check
              </button>
            </div>

            {/* Path validation status */}
            {pathStatus && (
              <div className={`mt-2 flex items-center gap-2 text-xs ${
                pathStatus.writable ? 'text-spotify-green' : 'text-red-400'
              }`}>
                {pathStatus.writable ? (
                  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>
                  </svg>
                )}
                <span>
                  {pathStatus.writable
                    ? pathStatus.created
                      ? `Directory created and writable: ${pathStatus.path}`
                      : `Directory exists and writable: ${pathStatus.path}`
                    : `Directory not writable: ${pathStatus.path}`
                  }
                </span>
              </div>
            )}
          </div>

          {/* Monitor Interval */}
          <div>
            <label className="block text-sm font-medium text-white mb-2">
              Monitor Interval
            </label>
            <p className="text-xs text-spotify-light-gray mb-3">
              How often to check playlists for new songs (in minutes)
            </p>
            <div className="flex items-center gap-3">
              <input
                type="number"
                value={monitorInterval}
                onChange={(e) => setMonitorInterval(Math.max(1, parseInt(e.target.value) || 1))}
                min={1}
                max={1440}
                className="w-24 px-4 py-2.5 bg-spotify-mid-gray border border-white/10 rounded-xl text-white text-sm focus:outline-none focus:border-spotify-green focus:ring-1 focus:ring-spotify-green transition-all"
              />
              <span className="text-sm text-spotify-light-gray">minutes</span>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="p-3 bg-red-900/30 border border-red-500/30 rounded-xl">
              <p className="text-sm text-red-300">{error}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-6 border-t border-white/5">
          <button
            onClick={onClose}
            className="px-5 py-2.5 text-sm text-spotify-light-gray hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-5 py-2.5 bg-spotify-green hover:bg-spotify-green-dark text-black font-semibold text-sm rounded-full transition-all disabled:opacity-50 flex items-center gap-2"
          >
            {saving ? (
              <>
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                Saving...
              </>
            ) : saved ? (
              <>
                <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
                </svg>
                Saved!
              </>
            ) : (
              'Save Settings'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
