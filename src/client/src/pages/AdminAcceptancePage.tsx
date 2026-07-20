import { useEffect, useState } from 'react';
import { getSlotValue } from '../shared/identity';
import { canAccessAcceptance } from '../shared/admin-acceptance';

type AcceptanceFixture = {
  label: string;
  description: string;
  href: string;
};

const DEFAULT_FIXTURES: AcceptanceFixture[] = [
  { label: '玩家邀请与准备', description: '登录、选预设角色、进入准备台。', href: '/player/join' },
  { label: '玩家叙事行动', description: '自然语言、风险确认、判定卡与地图投影。', href: '/player/join' },
  { label: '房主开局检查', description: '可开团剧本、玩家状态与开始门禁。', href: '/host/create' },
  { label: '剧本编译向导', description: '导入、质量审核、素材绑定与发布。', href: '/admin' },
];

export default function AdminAcceptancePage() {
  const [fixtures, setFixtures] = useState<AcceptanceFixture[]>(DEFAULT_FIXTURES);
  const [error, setError] = useState('');
  const [counts, setCounts] = useState<{ rooms: number; scenarios: number } | null>(null);
  const [retentionDays, setRetentionDays] = useState(90);
  const accountRaw = getSlotValue('account');
  let role: string | undefined;
  try {
    role = accountRaw ? JSON.parse(accountRaw).role : undefined;
  } catch {
    role = undefined;
  }

  useEffect(() => {
    const token = getSlotValue('account_token');
    if (!token) return;
    fetch('/api/admin/acceptance', { headers: { Authorization: `Bearer ${token}` } })
      .then(async (response) => {
        if (response.status === 404) return null;
        if (!response.ok) throw new Error('验收数据加载失败');
        return response.json();
      })
      .then((data) => {
        if (Array.isArray(data?.fixtures)) setFixtures(data.fixtures);
        if (data?.counts && typeof data.counts.rooms === 'number' && typeof data.counts.scenarios === 'number') {
          setCounts(data.counts);
        }
        if (typeof data?.retention_days === 'number') setRetentionDays(data.retention_days);
      })
      .catch((caught: Error) => setError(caught.message));
  }, []);

  if (!canAccessAcceptance(role)) {
    return (
      <div className="bh-page bh-page--narrow">
        <section className="bh-panel">
          <span className="bh-eyebrow">ADMIN ONLY</span>
          <h1 className="bh-panel-title">需要管理员权限</h1>
          <p className="bh-panel-desc">验收房、重置预检和系统工具只向管理员开放。</p>
          <a className="bh-button bh-button--yellow" href="/login" onClick={() => sessionStorage.setItem('login_return_to', '/admin/acceptance')}>登录管理员账号</a>
        </section>
      </div>
    );
  }

  return (
    <div className="bh-page">
      <section className="bh-acceptance-header">
        <div>
          <span className="bh-eyebrow">ADMIN ONLY</span>
          <h1 className="bh-panel-title">体验验收中心</h1>
          <p className="bh-panel-desc">按真实角色与测试房逐项检查页面流、状态反馈和信息投影。</p>
          {counts && <p className="bh-panel-desc">当前数据：{counts.rooms} 个房间 · {counts.scenarios} 个剧本 · 备份保留 {retentionDays} 天。</p>}
        </div>
        <a className="bh-button" href="/admin">返回后台</a>
      </section>
      {error && <div className="bh-error" role="alert">{error}</div>}
      <div className="bh-acceptance-grid">
        {fixtures.map((fixture) => (
          <article key={fixture.label} className="bh-panel bh-acceptance-card">
            <span className="bh-eyebrow">MANUAL CHECK</span>
            <h2>{fixture.label}</h2>
            <p>{fixture.description}</p>
            <a className="bh-button bh-button--yellow" href={fixture.href}>打开测试入口</a>
          </article>
        ))}
      </div>
    </div>
  );
}
