import { lazy, Suspense, useState } from 'react';
import { Routes, Route, Outlet, useLocation } from 'react-router-dom';
import Layout from './components/Layout';
import SettingsModal from './components/SettingsModal';
import { useHeaderContext } from './context/HeaderContext';

const SpotDownloadView = lazy(() => import('./views/SpotDownloadView'));
const MixtapeView = lazy(() => import('./views/MixtapeView'));
const LexiconView = lazy(() => import('./views/LexiconView'));

function RouteFallback() {
  return (
    <div className="flex items-center justify-center min-h-[40vh] text-spotify-light-gray text-sm">
      Loading…
    </div>
  );
}

function AppShell() {
  const { onGoHome } = useHeaderContext();
  const location = useLocation();
  const [settingsOpen, setSettingsOpen] = useState(false);
  return (
    <Layout
      onOpenSettings={() => setSettingsOpen(true)}
      onGoHome={onGoHome}
      showSettings
    >
      <Outlet />
      <SettingsModal isOpen={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </Layout>
  );
}

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route
          index
          element={
            <Suspense fallback={<RouteFallback />}>
              <SpotDownloadView />
            </Suspense>
          }
        />
        <Route
          path="mixtape"
          element={
            <Suspense fallback={<RouteFallback />}>
              <MixtapeView />
            </Suspense>
          }
        />
        <Route
          path="lexicon"
          element={
            <Suspense fallback={<RouteFallback />}>
              <LexiconView />
            </Suspense>
          }
        />
      </Route>
    </Routes>
  );
}
