import { useState, useEffect } from 'react';
import { getSlotValue, setSlotValue } from '../shared/identity';
import { getScenarioLaunchBadge } from '../shared/host-scenario-card';

type LaunchableScenario = {
  scenario_id: string;
  title: string;
  quality_level?: string;
  completeness?: number;
  risk_warning?: string;
};

export default function HostCreate() {
  const [roomId, setRoomId] = useState('');
  const [scenarios, setScenarios] = useState<LaunchableScenario[]>([]);
  const [selectedScenario, setSelectedScenario] = useState('');
  const [account, setAccount] = useState<any>(null);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const token = getSlotValue('account_token');
    const accRaw = getSlotValue('account');
    if (token && accRaw) {
      try { setAccount(JSON.parse(accRaw)); } catch { setAccount(null); }
    }
    fetch('/api/scenarios/available', {
      headers: { Authorization: `Bearer ${getSlotValue('account_token') || ''}` },
    })
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        const list = Array.isArray(data) ? data : (data.scenarios || []);
        setScenarios(list);
      })
      .catch(() => {});
  }, []);

  const create = async () => {
    if (!selectedScenario) { setError('请选择剧本'); return; }
    setCreating(true); setError('');
    try {
      const res = await fetch('/api/rooms', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${getSlotValue('account_token') || ''}`,
        },
        body: JSON.stringify({ scenario_id: selectedScenario }),
      });
      const data = await res.json();
      if (!res.ok) { setError(data.detail || '创建失败'); setCreating(false); return; }
      setSlotValue('owner_token', data.owner_token);
      setRoomId(data.room_id);
    } catch (e: any) {
      setError(e.message || '网络错误');
    }
    setCreating(false);
  };

  if (!account) {
    sessionStorage.setItem('login_return_to', '/host/create');
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">KEEPER PRIME</span>
        <h2 className="bh-panel-title">创建守密人房间</h2>
        <p style={{ color: 'var(--bh-dim)', marginBottom: 16 }}>创建房间需要登录房主或管理员账号。</p>
        <a className="bh-button bh-button--yellow" href="/login">登录 / 注册</a>
      </section>
    );
  }

  if (account.role !== 'host' && account.role !== 'admin') {
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">KEEPER PRIME</span>
        <h2 className="bh-panel-title">需要房主权限</h2>
        <p style={{ color: 'var(--bh-red)', marginBottom: 16 }}>
          当前账号角色为 "{account.role}"，需要 "host" 或 "admin" 才能创建房间。请联系管理员提升权限。
        </p>
        <a className="bh-button" href="/">返回首页</a>
      </section>
    );
  }

  if (roomId) {
    return (
      <section className="bh-panel">
        <span className="bh-eyebrow">ROOM READY</span>
        <h2 className="bh-panel-title">房间已创建</h2>
        <p>房间号：<strong>{roomId}</strong></p>
        <div className="bh-action-row">
          <a className="bh-button bh-button--yellow" href={`/host/${roomId}`}>进入大厅</a>
          <a className="bh-button bh-button--black" href={`/host/${roomId}/stage`}>打开主舞台</a>
        </div>
      </section>
    );
  }

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">KEEPER PRIME</span>
      <h2 className="bh-panel-title">创建守密人房间</h2>
      <p style={{ fontSize: 13, color: 'var(--bh-dim)', marginBottom: 8 }}>
        已登录：{account.username} ({account.role === 'admin' ? '管理员' : '房主'})
      </p>
      <div style={{ marginBottom: 16 }}>
        <label style={{ display: 'block', fontWeight: 700, marginBottom: 4, fontSize: 13 }}>选择已发布剧本</label>
        {scenarios.length === 0 ? (
          <p style={{ color: 'var(--bh-dim)', fontSize: 13, padding: '12px 0' }}>暂无可用剧本，请管理员先导入剧本。</p>
        ) : (
          <div className="bh-preset-list" aria-label="可开团剧本">
            {scenarios.map((scenario) => {
              const badge = getScenarioLaunchBadge(scenario);
              return (
                <button
                  key={scenario.scenario_id}
                  type="button"
                  className={`bh-preset-card ${selectedScenario === scenario.scenario_id ? 'bh-preset-card--selected' : ''}`}
                  onClick={() => { setSelectedScenario(scenario.scenario_id); setError(''); }}
                >
                  <strong>{scenario.title || scenario.scenario_id}</strong>
                  <span>{badge.label}</span>
                  <small>{badge.detail}</small>
                  {typeof scenario.completeness === 'number' && <small>编译完整度：{Math.round(scenario.completeness * 100)}%</small>}
                </button>
              );
            })}
          </div>
        )}
      </div>
      {error && <p style={{ color: 'var(--bh-red)', fontSize: 13, marginBottom: 8 }}>{error}</p>}
      <button
        className="bh-button bh-button--yellow"
        onClick={create}
        disabled={creating || !selectedScenario}
        type="button"
      >
        {creating ? '创建中...' : '创建房间'}
      </button>
    </section>
  );
}
