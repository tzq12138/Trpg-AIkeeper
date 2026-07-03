import { useEffect, useState } from 'react';
import HostStage from './pages/HostStage';
import HostLobby from './pages/HostLobby';
import AdminDashboard from './pages/AdminDashboard';
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
  return (
    <div className="bh-grid-links">
      <a className="bh-link-card bh-link-card--black" href="/admin">
        <strong>管理后台</strong>
        <span>ROOMS / SCENARIOS</span>
      </a>
      <a className="bh-link-card bh-link-card--yellow" href="/rag-test">
        <strong>规则书 RAG</strong>
        <span>RULEBOOK LAB</span>
      </a>
      <a className="bh-link-card" href="/host/create">
        <strong>创建房间</strong>
        <span>HOST / KEEPER</span>
      </a>
      <a className="bh-link-card" href="/player/join">
        <strong>加入房间</strong>
        <span>PLAYER / INVESTIGATOR</span>
      </a>
    </div>
  );
}

// HostCreate extracted to pages/HostCreate.tsx
