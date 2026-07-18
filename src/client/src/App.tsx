import { useEffect, useState } from 'react';
import HostStage from './pages/HostStage';
import HostLobby from './pages/HostLobby';
import AdminDashboard from './pages/AdminDashboard';
import AdminAcceptancePage from './pages/AdminAcceptancePage';
import RagTestPage from './pages/RagTestPage';
import PlayerActionPage from './pages/PlayerActionPage';
import PlayerLobby from './pages/PlayerLobby';
import PlayerJoinPage from './pages/PlayerJoinPage';
import CharacterBuilderPage from './pages/CharacterBuilderPage';
import LoginPage from './pages/LoginPage';
import HostCreate from './pages/HostCreate';
import IdentitySwitcher from './components/IdentitySwitcher';
import { BauhausPage } from './components/BauhausShell';
import { getCurrentRoute, type AppRoute } from './navigation';
import { getSlotValue } from './shared/identity';
import { getHomeTasks } from './shared/home-navigation';

export default function App() {
  const [route, setRoute] = useState<AppRoute>(getCurrentRoute());

  useEffect(() => {
    const handler = () => setRoute(getCurrentRoute());
    window.addEventListener('popstate', handler);
    return () => window.removeEventListener('popstate', handler);
  }, []);

  if (route.page === 'host-stage') {
    return <HostStage roomId={route.param} />;
  }
  if (route.page === 'admin') {
    return <AdminDashboard />;
  }
  if (route.page === 'admin-acceptance') {
    return <AdminAcceptancePage />;
  }
  if (route.page === 'rag-test') {
    return <RagTestPage />;
  }
  if (route.page === 'player-lobby') {
    return <PlayerLobby roomId={route.param} />;
  }
  if (route.page === 'player-action') {
    return <PlayerActionPage roomId={route.param} />;
  }
  if (route.page === 'player-builder') {
    return (
      <BauhausPage narrow>
        <div className="bh-home" style={{ marginTop: 8 }}>
          <CharacterBuilderPage
            onComplete={(data) => {
              sessionStorage.setItem('builder_character', JSON.stringify(data));
              window.location.href = '/player/join?source=builder';
            }}
            onCancel={() => { window.location.href = '/player/join'; }}
          />
        </div>
      </BauhausPage>
    );
  }
  if (route.page === 'login') {
    return (
      <BauhausPage narrow>
        <div className="bh-home" style={{ marginTop: 8 }}>
          <div className="bh-logo-row">
            <div className="bh-logo-mark">AK</div>
            <div>
              <h1 className="bh-title" style={{ fontSize: 42 }}>AI-Keeper</h1>
              <p className="bh-subtitle">Account</p>
            </div>
          </div>
          <LoginPage />
        </div>
      </BauhausPage>
    );
  }

  return (
    <BauhausPage narrow>
      <div className="bh-home">
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
          <IdentitySwitcher />
        </div>
        <div className="bh-logo-row">
          <div className="bh-logo-mark">AK</div>
          <div>
            <h1 className="bh-title">AI-Keeper</h1>
            <p className="bh-subtitle">Call of Cthulhu tabletop terminal</p>
          </div>
        </div>
        {route.page === 'home' && <Home />}
        {route.page === 'host-create' && <HostCreate />}
        {route.page === 'host-lobby' && <HostLobby roomId={route.param} />}
        {route.page === 'player-join' && <PlayerJoinPage />}
      </div>
    </BauhausPage>
  );
}

function Home() {
  let role = '';
  try {
    role = JSON.parse(getSlotValue('account') || '{}').role || '';
  } catch {
    role = '';
  }

  return (
    <div className="bh-grid-links">
      {getHomeTasks(role).map((task) => (
        <a
          key={task.href}
          className={`bh-link-card${task.tone === 'yellow' ? ' bh-link-card--yellow' : ''}${task.tone === 'black' ? ' bh-link-card--black' : ''}`}
          href={task.href}
        >
          <strong>{task.label}</strong>
          <span>{task.eyebrow}</span>
        </a>
      ))}
    </div>
  );
}

// HostCreate extracted to pages/HostCreate.tsx
