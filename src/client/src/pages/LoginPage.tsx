import { useState } from 'react';
import { setSlotValue } from '../shared/identity';

export default function LoginPage() {
  const [tab, setTab] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!username.trim() || !password.trim()) {
      setError('请填写用户名和密码');
      return;
    }
    setError('');
    setLoading(true);

    try {
      const endpoint = tab === 'login' ? '/api/auth/login' : '/api/auth/register';
      const body: Record<string, string> = { username: username.trim(), password };
      if (tab === 'register' && displayName.trim()) {
        body.display_name = displayName.trim();
      }

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(String(data.detail || '操作失败'));
        return;
      }

      const data = await res.json();
      setSlotValue('account_token', data.token);
      setSlotValue('account', JSON.stringify({
        account_id: data.account_id,
        username: data.username,
        display_name: data.display_name,
        role: data.role || 'player',
      }));

      // Redirect to previous page or home (only allow relative paths)
      const raw = sessionStorage.getItem('login_return_to') || '/';
      sessionStorage.removeItem('login_return_to');
      const returnTo = raw.startsWith('/') && !raw.startsWith('//') ? raw : '/';
      window.location.href = returnTo;
    } catch {
      setError('网络错误，请确认后端服务已启动。');
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="bh-panel" style={{ maxWidth: 420, margin: '0 auto' }}>
      <span className="bh-eyebrow">ACCOUNT</span>
      <h2 className="bh-panel-title">{tab === 'login' ? '登录' : '注册'}</h2>

      <div className="bh-source-toggle" style={{ marginBottom: 16 }}>
        <button
          className={`bh-button ${tab === 'login' ? 'bh-button--yellow' : ''}`}
          onClick={() => { setTab('login'); setError(''); }}
        >
          登录
        </button>
        <button
          className={`bh-button ${tab === 'register' ? 'bh-button--yellow' : ''}`}
          onClick={() => { setTab('register'); setError(''); }}
        >
          注册
        </button>
      </div>

      <div className="bh-form" style={{ width: '100%' }}>
        <label className="bh-field">
          <span>用户名</span>
          <input
            className="bh-input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="登录名"
          />
        </label>
        <label className="bh-field">
          <span>密码</span>
          <input
            className="bh-input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码（PBKDF2 加密存储）"
          />
        </label>
        {tab === 'register' && (
          <label className="bh-field">
            <span>显示名称（可选）</span>
            <input
              className="bh-input"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="对他人显示的名字"
            />
          </label>
        )}
      </div>

      {error && <p className="bh-error" style={{ marginTop: 12 }}>{error}</p>}

      <button
        className="bh-button bh-button--yellow"
        style={{ width: '100%', marginTop: 16 }}
        disabled={loading}
        onClick={handleSubmit}
      >
        {loading ? '处理中...' : tab === 'login' ? '登录' : '注册'}
      </button>

      <p style={{ marginTop: 16, fontSize: 12, color: 'var(--bh-muted)', fontWeight: 700, textAlign: 'center' }}>
        邀请房间需要账号；登录或注册后会自动返回原房间，并可恢复历史角色。
      </p>
    </section>
  );
}
