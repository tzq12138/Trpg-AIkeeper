import { useState, useEffect } from 'react';

const TOKEN_KEY = 'account_token';
const ACCOUNT_KEY = 'account';

function api(path: string, opts?: RequestInit) {
  const token = localStorage.getItem(TOKEN_KEY) || '';
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((opts?.headers as Record<string, string>) || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return fetch(path, { ...opts, headers }).then((r) => {
    if (!r.ok) return r.json().then((d) => { throw new Error(d.detail || `${r.status}`); });
    return r.json();
  });
}

type AdminTab = 'overview' | 'rooms' | 'scenarios' | 'characters' | 'accounts';

export default function AdminDashboard() {
  const [tab, setTab] = useState<AdminTab>('overview');
  const [authed, setAuthed] = useState(false);
  const [checking, setChecking] = useState(true);

  useEffect(() => {
    api('/api/admin/overview')
      .then(() => setAuthed(true))
      .catch(() => setAuthed(false))
      .finally(() => setChecking(false));
  }, []);

  if (checking) return <div className="bh-page bh-page--narrow"><div className="bh-home"><div className="bh-muted-box">验证管理员身份...</div></div></div>;

  if (!authed) {
    return (
      <div className="bh-page bh-page--narrow">
        <div className="bh-home">
          <section className="bh-panel">
            <span className="bh-eyebrow">ADMIN</span>
            <h2 className="bh-panel-title">管理后台</h2>
            <p className="bh-error">需要管理员账号登录。</p>
            <a className="bh-button bh-button--yellow" href="/login" onClick={() => sessionStorage.setItem('login_return_to', '/admin')}>去登录</a>
          </section>
        </div>
      </div>
    );
  }

  const account = JSON.parse(localStorage.getItem(ACCOUNT_KEY) || '{}');

  const tabs: Array<{ key: AdminTab; label: string; eyebrow: string }> = [
    { key: 'overview', label: '概览', eyebrow: 'OVERVIEW' },
    { key: 'rooms', label: '房间', eyebrow: 'ROOMS' },
    { key: 'scenarios', label: '剧本', eyebrow: 'SCENARIOS' },
    { key: 'characters', label: '角色', eyebrow: 'CHARS' },
    { key: 'accounts', label: '账号', eyebrow: 'ACCOUNTS' },
  ];

  return (
    <div className="bh-page" style={{ padding: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '16px 24px', borderBottom: '6px solid var(--bh-black)', background: 'var(--bh-paper)' }}>
        <div className="bh-logo-mark" style={{ width: 44, height: 44, fontSize: 20 }}>AK</div>
        <strong style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontSize: 22 }}>ADMIN</strong>
        <span style={{ flex: 1 }} />
        <span style={{ fontWeight: 800, fontSize: 13 }}>{account.display_name || account.username}</span>
        <button className="bh-button" style={{ minHeight: 36, padding: '6px 12px', fontSize: 12 }} onClick={() => { localStorage.removeItem(TOKEN_KEY); localStorage.removeItem(ACCOUNT_KEY); window.location.href = '/'; }}>登出</button>
      </div>
      <div style={{ display: 'flex', gap: 0, borderBottom: '4px solid var(--bh-black)' }}>
        {tabs.map((t) => (
          <button key={t.key} className={`bh-tab ${tab === t.key ? 'bh-tab--active' : ''}`} style={{ borderBottom: 0 }} onClick={() => setTab(t.key)} aria-selected={tab === t.key}>
            <span className="bh-tab-eyebrow">{t.eyebrow}</span>
            {t.label}
          </button>
        ))}
      </div>
      <div style={{ padding: 24, maxWidth: 1200 }}>
        {tab === 'overview' && <OverviewPanel />}
        {tab === 'rooms' && <RoomsPanel />}
        {tab === 'scenarios' && <ScenariosPanel />}
        {tab === 'characters' && <CharactersPanel />}
        {tab === 'accounts' && <AccountsPanel />}
      </div>
    </div>
  );
}

// ── Overview ──

function OverviewPanel() {
  const [data, setData] = useState<Record<string, number> | null>(null);
  useEffect(() => { api('/api/admin/overview').then(setData).catch(() => {}); }, []);
  if (!data) return <div className="bh-muted-box">加载中...</div>;

  const cards: Array<{ label: string; value: number; eyebrow: string }> = [
    { label: '总房间', value: data.total_rooms, eyebrow: 'ROOMS' },
    { label: '进行中', value: data.active_rooms, eyebrow: 'ACTIVE' },
    { label: '注册账号', value: data.total_accounts, eyebrow: 'USERS' },
    { label: '在线角色', value: data.online_players, eyebrow: 'ONLINE' },
    { label: '待处理行动', value: data.pending_actions, eyebrow: 'QUEUE' },
  ];

  return (
    <section>
      <h2 className="bh-panel-title">全局概览</h2>
      <div className="bh-grid-links" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))' }}>
        {cards.map((c) => (
          <div key={c.eyebrow} className="bh-link-card" style={{ minHeight: 100 }}>
            <span className="bh-eyebrow">{c.eyebrow}</span>
            <strong>{c.value}</strong>
            <span>{c.label}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Rooms ──

function RoomsPanel() {
  const [rooms, setRooms] = useState<any[]>([]);
  const [selected, setSelected] = useState<string>('');
  const [detail, setDetail] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    api('/api/admin/rooms').then(setRooms).finally(() => setLoading(false));
  };
  useEffect(load, []);

  const showDetail = (id: string) => {
    setSelected(id);
    api(`/api/admin/rooms/${id}`).then(setDetail).catch(() => setDetail(null));
  };

  const patchRoom = async (id: string, status: string) => {
    await api(`/api/admin/rooms/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) });
    load();
    showDetail(id);
  };

  const statusColors: Record<string, string> = {
    draft: 'var(--bh-muted)', lobby: 'var(--bh-blue)', active: 'var(--bh-yellow-dim)',
    paused: 'var(--bh-yellow)', completed: 'var(--bh-red)', archived: 'var(--bh-paper-3)',
  };
  const statusLabel: Record<string, string> = {
    draft: '草稿', lobby: '大厅等待', active: '进行中', paused: '已暂停', completed: '已完成', archived: '已归档',
  };

  const [showCreate, setShowCreate] = useState(false);
  const [newRoomScenarioId, setNewRoomScenarioId] = useState('');
  const [newRoomOwnerId, setNewRoomOwnerId] = useState('');
  const [scenarioList, setScenarioList] = useState<any[]>([]);
  const [accountList, setAccountList] = useState<any[]>([]);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState('');

  const handleCreateRoom = async () => {
    if (!newRoomScenarioId) { setCreateError('请选择剧本'); return; }
    setCreating(true); setCreateError('');
    try {
      const token = localStorage.getItem(TOKEN_KEY) || '';
      const res = await fetch('/api/rooms', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
        body: JSON.stringify({ scenario_id: newRoomScenarioId, owner_account_id: newRoomOwnerId || undefined, spoiler_level: 'standard' }),
      });
      if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || '创建失败'); }
      const data = await res.json();
      setShowCreate(false); setNewRoomScenarioId(''); setNewRoomOwnerId('');
      load(); showDetail(data.room_id);
    } catch (e: any) { setCreateError(e.message); }
    setCreating(false);
  };

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 className="bh-panel-title">房间管理</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="bh-button bh-button--yellow" onClick={() => { setShowCreate(!showCreate); if (!showCreate) { api('/api/admin/scenarios').then(setScenarioList); api('/api/admin/accounts').then(setAccountList); } }}>{showCreate ? '取消' : '新建房间'}</button>
          <button className="bh-button" onClick={load} disabled={loading}>刷新</button>
        </div>
      </div>

      {showCreate && (
        <div className="bh-panel" style={{ marginTop: 8, padding: 12 }}>
          <span className="bh-eyebrow">新建房间</span>
          <select className="bh-input" style={{ marginTop: 8 }} value={newRoomScenarioId} onChange={(e) => setNewRoomScenarioId(e.target.value)}>
            <option value="">-- 选择剧本 --</option>
            {scenarioList.map((s: any) => <option key={s.scenario_id} value={s.scenario_id}>{s.title || s.scenario_id}</option>)}
          </select>
          <select className="bh-input" style={{ marginTop: 4 }} value={newRoomOwnerId} onChange={(e) => setNewRoomOwnerId(e.target.value)}>
            <option value="">-- 房主账号（默认自己） --</option>
            {accountList.map((a: any) => <option key={a.account_id} value={a.account_id}>{a.display_name || a.username} ({a.role})</option>)}
          </select>
          <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
            <button className="bh-button bh-button--yellow" onClick={handleCreateRoom} disabled={creating}>
              {creating ? '创建中...' : '确认创建'}
            </button>
            {createError && <span style={{ color: 'var(--bh-red)', fontSize: 12 }}>{createError}</span>}
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: selected ? '1fr 1fr' : '1fr', gap: 16, marginTop: 16 }}>
        <div className="bh-preset-list">
          {rooms.map((r) => (
            <button key={r.room_id} className={`bh-preset-card ${selected === r.room_id ? 'bh-preset-card--selected' : ''}`}
              onClick={() => showDetail(r.room_id)}>
              <strong>{r.room_id}</strong>
              <span>{r.scenario_title || '无剧本'}</span>
              <small style={{ color: statusColors[r.status] || 'var(--bh-muted)' }}>{r.status}</small>
            </button>
          ))}
        </div>

        {selected && detail && (
          <div className="bh-preview-box">
            <span className="bh-eyebrow">房间详情</span>
            <h3>{detail.room_id}</h3>
            <p>剧本：{detail.scenario_title || '未指定'}</p>
            <p>状态：<strong style={{ color: statusColors[detail.status] }}>{statusLabel[detail.status] || detail.status}</strong></p>
            <p>创建时间：{detail.created_at}</p>
            {detail.started_at && <p>开始时间：{detail.started_at}</p>}

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
              {['draft', 'lobby', 'active', 'paused', 'completed', 'archived'].map((s) => (
                <button key={s} className="bh-button" style={{ minHeight: 32, padding: '4px 10px', fontSize: 12 }}
                  disabled={detail.status === s} onClick={() => patchRoom(selected, s)}>
                  {statusLabel[s] || s}
                </button>
              ))}
            </div>

            <div style={{ marginTop: 12, borderTop: '3px solid var(--bh-black)', paddingTop: 8 }}>
              <strong>玩家 ({detail.characters?.length || 0})</strong>
              {detail.characters?.map((c: any) => {
                const pStatusLabels: Record<string, string> = { joined: '已加入', active: '在线', pending_approval: '待审批', removed: '已移除', left: '已离开' };
                return (
                <div key={c.character_id} className="bh-skill-row" style={{ padding: '4px 0' }}>
                  <span>{c.investigator_name || c.player_name}</span>
                  <span style={{ fontSize: 11 }}>HP {c.hp}/{c.max_hp}</span>
                  <span style={{ fontSize: 11 }}>{c.is_ready ? '[OK]' : '[--]'} {pStatusLabels[c.status] || c.status}</span>
                </div>
                );
              })}
            </div>

            <div className="bh-action-row" style={{ marginTop: 12 }}>
              <a className="bh-button bh-button--yellow" href={`/host/${detail.room_id}`}>房主大厅</a>
              <a className="bh-button bh-button--yellow" href={`/host/${detail.room_id}/stage`}>房主舞台</a>
              <a className="bh-button" href={`/player/${detail.room_id}`}>玩家入口</a>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Scenarios ──

function ScenariosPanel() {
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [assets, setAssets] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);

  const loadScenarios = () => api('/api/admin/scenarios').then(setScenarios);
  useEffect(() => { loadScenarios(); }, []);

  const loadAssets = (sid: string) => {
    setSelectedId(sid);
    api(`/api/admin/scenarios/${sid}/assets`).then(setAssets).catch(() => setAssets([]));
  };

  const uploadAsset = async (sid: string, file: File) => {
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const token = localStorage.getItem(TOKEN_KEY) || '';
      await fetch(`/api/admin/scenarios/${sid}/assets`, { method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form });
      loadAssets(sid);
    } catch { /* ignore */ }
    setUploading(false);
  };

  const deleteAsset = async (sid: string, aid: string) => {
    await api(`/api/admin/scenarios/${sid}/assets/${aid}`, { method: 'DELETE' });
    loadAssets(sid);
  };

  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState('');

  const handleImportPdf = async (file: File) => {
    setImporting(true);
    setImportError('');
    const form = new FormData();
    form.append('file', file);
    try {
      const token = localStorage.getItem(TOKEN_KEY) || '';
      const res = await fetch('/api/admin/scenarios/import-pdf', {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: form,
      });
      if (!res.ok) { const err = await res.json().catch(() => ({})); throw new Error(err.detail || '导入失败'); }
      await loadScenarios();
      // Auto-select the newly imported scenario
      const latest = await api('/api/admin/scenarios');
      if (latest.length > 0) { const s = latest[0]; setSelectedId(s.scenario_id); loadAssets(s.scenario_id); }
    } catch (e: any) {
      setImportError(e.message || '导入失败，请检查文件格式');
    }
    setImporting(false);
  };

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <h2 className="bh-panel-title">剧本 & 素材</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <label className="bh-button bh-button--yellow" style={{ cursor: 'pointer' }}>
            {importing ? '导入中...' : '导入剧本 PDF'}
            <input type="file" accept=".pdf" style={{ display: 'none' }} disabled={importing}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleImportPdf(f); e.target.value = ''; }} />
          </label>
          <button className="bh-button" onClick={loadScenarios}>刷新</button>
        </div>
      </div>
      {importError && <div className="bh-muted-box" style={{ color: 'var(--bh-red)', marginTop: 8 }}>{importError}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: selectedId ? '1fr 1fr' : '1fr', gap: 16, marginTop: 16 }}>
        <div className="bh-preset-list">
          {scenarios.length === 0 ? (
            <div className="bh-muted-box" style={{ padding: 24, textAlign: 'center' }}>
              还没有剧本，点击"导入剧本 PDF"开始
            </div>
          ) : (
            scenarios.map((s) => (
            <button key={s.scenario_id} className={`bh-preset-card ${selectedId === s.scenario_id ? 'bh-preset-card--selected' : ''}`}
              onClick={() => loadAssets(s.scenario_id)}>
              <strong>{s.title || s.scenario_id}</strong>
              <span style={{ fontSize: 10, opacity: 0.6 }}>{s.import_status === 'structured' ? '已结构化' : s.import_status}</span>
            </button>
          )))}
        </div>

        {selectedId && (
          <div className="bh-preview-box">
            <span className="bh-eyebrow">ASSETS</span>
            <h3>{scenarios.find((s) => s.scenario_id === selectedId)?.title || selectedId}</h3>

            <label className="bh-upload-box">
              <span>{uploading ? '上传中...' : '上传素材文件'}</span>
              <input type="file" accept="image/*,audio/*,video/*,.pdf" multiple disabled={uploading}
                onChange={(e) => { if (e.target.files) { for (let i = 0; i < e.target.files.length; i++) uploadAsset(selectedId, e.target.files[i]); } e.target.value = ''; }} />
            </label>

            <div className="bh-preset-list">
              {assets.length === 0 && <div className="bh-muted-box">暂无素材</div>}
              {assets.map((a: any) => (
                <div key={a.asset_id} className="bh-skill-row" style={{ padding: '8px' }}>
                  <span>{a.original_name}</span>
                  <span style={{ fontSize: 11, color: 'var(--bh-muted)' }}>{(a.file_size / 1024).toFixed(0)} KB</span>
                  <button className="bh-button bh-button--red" style={{ minHeight: 28, padding: '2px 8px', fontSize: 11 }}
                    onClick={() => deleteAsset(selectedId, a.asset_id)}>删除</button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ── Characters ──

function CharactersPanel() {
  const [chars, setChars] = useState<any[]>([]);
  const [roomFilter, setRoomFilter] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, any>>({});

  const load = () => api(`/api/admin/characters?room_id=${roomFilter}`).then(setChars);
  useEffect(() => { load(); }, [roomFilter]);

  const saveChar = async (id: string) => {
    await api(`/api/admin/characters/${id}`, { method: 'PATCH', body: JSON.stringify(form) });
    setEditing(null);
    load();
  };

  const startEdit = (c: any) => {
    setEditing(c.character_id);
    const xlsx = c.xlsx_data || {};
    setForm({ hp: xlsx.hp, max_hp: xlsx.max_hp, san: xlsx.san, max_san: xlsx.max_san, mp: xlsx.mp, max_mp: xlsx.max_mp, luck: xlsx.luck, is_ready: c.is_ready, status: c.status });
  };

  return (
    <section>
      <h2 className="bh-panel-title">角色管理</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input className="bh-input" placeholder="按房间码过滤" value={roomFilter} onChange={(e) => setRoomFilter(e.target.value)} style={{ width: 200 }} />
        <button className="bh-button" onClick={load}>刷新</button>
      </div>

      <div className="bh-preset-list">
        {chars.map((c) => (
          <div key={c.character_id} className="bh-preset-card" style={{ textAlign: 'left' }}>
            <strong>{c.summary?.investigator_name || c.player_name}</strong>
            <span>{c.player_name} | 房间 {c.room_id} | {c.status}</span>
            <small>HP:{c.summary?.hp} SAN:{c.summary?.san} Ready:{c.is_ready ? 'Y' : 'N'}</small>

            {editing === c.character_id ? (
              <div style={{ display: 'grid', gap: 6, marginTop: 8, padding: 8, border: '3px solid var(--bh-black)', background: 'var(--bh-paper)' }}>
                {['hp', 'max_hp', 'san', 'max_san', 'mp', 'max_mp', 'luck'].map((k) => (
                  <label key={k} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                    <span style={{ width: 50 }}>{k}</span>
                    <input className="bh-input" type="number" value={form[k] || 0} style={{ padding: '4px 8px', width: 80 }}
                      onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} />
                  </label>
                ))}
                <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                  <span style={{ width: 50 }}>Ready</span>
                  <input type="checkbox" checked={!!form.is_ready} onChange={(e) => setForm({ ...form, is_ready: e.target.checked })} />
                </label>
                <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}>
                  <span style={{ width: 50 }}>状态</span>
                  <select className="bh-input" style={{ padding: '4px 8px', width: 100 }} value={form.status || 'active'}
                    onChange={(e) => setForm({ ...form, status: e.target.value })}>
                    <option value="active">active</option>
                    <option value="removed">removed</option>
                  </select>
                </label>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button className="bh-button bh-button--yellow" style={{ minHeight: 28, fontSize: 12, padding: '2px 10px' }} onClick={() => saveChar(c.character_id)}>保存</button>
                  <button className="bh-button" style={{ minHeight: 28, fontSize: 12, padding: '2px 10px' }} onClick={() => setEditing(null)}>取消</button>
                </div>
              </div>
            ) : (
              <button className="bh-button" style={{ minHeight: 28, fontSize: 11, padding: '2px 10px', marginTop: 6 }}
                onClick={() => startEdit(c)}>编辑</button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Accounts ──

function AccountsPanel() {
  const [accounts, setAccounts] = useState<any[]>([]);
  const load = () => api('/api/admin/accounts').then(setAccounts);
  useEffect(() => { load(); }, []);

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 className="bh-panel-title">账号管理</h2>
        <button className="bh-button" onClick={load}>刷新</button>
      </div>
      <div className="bh-preset-list" style={{ marginTop: 16 }}>
        {accounts.map((a) => (
          <div key={a.account_id} className="bh-preset-card" style={{ textAlign: 'left' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <strong>{a.display_name || a.username}</strong>
                <span>{a.username}</span>
                <small>角色：{a.role} | 最后活跃：{a.last_seen_at || '从未'}</small>
              </div>
              {a.role === 'player' && (
                <button
                  className="bh-button bh-button--yellow"
                  style={{ fontSize: 11, padding: '4px 8px' }}
                  onClick={async () => {
                    await api('/api/admin/accounts/' + a.account_id, {
                      method: 'PATCH',
                      body: JSON.stringify({ role: 'host' }),
                    });
                    load();
                  }}
                >
                  提升为房主
                </button>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
