import { useState, useEffect } from 'react';
import { getSlotValue, setSlotValue } from '../shared/identity';
import { canExecuteGlobalReset } from '../shared/reset-workflow';
import { getScenarioPublishGate } from '../shared/scenario-publish-gate';
import { SCENARIO_WORKFLOW_STEPS, type ScenarioWorkflowStep } from '../shared/scenario-workflow';
import { ScenarioReviewWorkbench } from '../components/ScenarioReviewWorkbench';

function api(path: string, opts?: RequestInit) {
  const token = getSlotValue('account_token') || '';
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

type AdminTab = 'overview' | 'rooms' | 'scenarios' | 'systemTools' | 'characters' | 'accounts';

export type AiProviderConfig = {
  provider_config_id: string;
  name: string;
  api_base_url: string;
  protocol: 'responses' | 'chat_completions';
  model: string;
  supports_image: boolean;
  has_api_key: boolean;
  key_mask: string;
  is_active: boolean;
  test_status: string;
  last_tested_at: string;
  last_test_latency_ms: number | null;
};

type AiProviderDraft = {
  name: string;
  apiBaseUrl: string;
  protocol: 'responses' | 'chat_completions';
  model: string;
  apiKey: string;
  supportsImage: boolean;
};

type ScenarioSummary = {
  scenario_id: string;
  title?: string;
  import_status?: string;
  status?: string;
  publish_status?: string;
  latest_import_job_id?: string;
  latest_import_job_status?: string;
  latest_import_job_retryable?: boolean;
};

type ScenarioVersion = {
  scenario_version_id: string;
  version_number?: number;
  status?: string;
  created_at?: string;
  reviewed_at?: string;
  published_at?: string;
  is_active?: boolean;
  quality_report?: Record<string, any>;
  review_notes?: Record<string, any> | string;
};

type ScenarioVersionDetail = ScenarioVersion & {
  prep_package?: Record<string, any>;
};

type ScenarioStatusMeta = {
  label: string;
  color: string;
  eyebrow: string;
};

export const SCENARIO_IMPORT_ENDPOINT = '/api/scenarios/import';
export const SCENARIO_IMPORT_ACCEPT = '.pdf,.docx,.png,.jpg,.jpeg,.webp';
export const SCENARIO_ROOM_OPTIONS_ENDPOINT = '/api/scenarios/available';
export const AI_PROVIDER_ENDPOINT = '/api/admin/ai/providers';
export const ADMIN_TABS: Array<{ key: AdminTab; label: string; eyebrow: string }> = [
  { key: 'overview', label: '概览', eyebrow: 'OVERVIEW' },
  { key: 'rooms', label: '房间', eyebrow: 'ROOMS' },
  { key: 'scenarios', label: '剧本', eyebrow: 'SCENARIOS' },
  { key: 'systemTools', label: '系统工具', eyebrow: 'TOOLS' },
  { key: 'characters', label: '角色', eyebrow: 'CHARS' },
  { key: 'accounts', label: '账号', eyebrow: 'ACCOUNTS' },
];

const DEFAULT_LICENSE_TYPE = 'authorized';
const REDACTED_PATH = '[已隐藏路径]';

const scenarioStatusMetaMap: Record<string, ScenarioStatusMeta> = {
  parsing: { label: '解析中', color: 'var(--bh-blue)', eyebrow: 'PARSING' },
  draft_review: { label: '待复核', color: 'var(--bh-yellow)', eyebrow: 'REVIEW' },
  draft_ready: { label: '已生成草稿版本', color: 'var(--bh-blue)', eyebrow: 'READY' },
  awaiting_provider: { label: '等待上游处理', color: 'var(--bh-paper-3)', eyebrow: 'WAITING' },
  failed: { label: '失败', color: 'var(--bh-red)', eyebrow: 'FAILED' },
  published: { label: '已发布', color: 'var(--bh-blue)', eyebrow: 'PUBLISHED' },
  structured: { label: '已结构化', color: 'var(--bh-blue)', eyebrow: 'READY' },
  draft: { label: '草稿', color: 'var(--bh-yellow-dim)', eyebrow: 'DRAFT' },
};

function getAuthHeader() {
  const token = getSlotValue('account_token') || '';
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

function normalizeScenarioStatus(status?: string) {
  return status || 'draft';
}

export function getScenarioStatusMeta(status?: string): ScenarioStatusMeta {
  const normalized = normalizeScenarioStatus(status);
  return scenarioStatusMetaMap[normalized] || {
    label: normalized,
    color: 'var(--bh-muted)',
    eyebrow: 'STATUS',
  };
}

function coerceErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  if (typeof error === 'string') return error;
  return '操作失败，请稍后重试';
}

export function sanitizeAdminScenarioError(error: unknown) {
  return coerceErrorMessage(error)
    .replace(/[A-Za-z]:\\[^\r\n]*/g, REDACTED_PATH)
    .replace(/\\\\[^\r\n]*/g, REDACTED_PATH)
    .replace(/\/(?:[^/\s]+\/)+[^/\s]+/g, REDACTED_PATH);
}

export function buildScenarioImportFormData({
  files,
  title,
  licenseType,
  licenseRef,
  scenarioId,
}: {
  files: Array<File | Blob>;
  title: string;
  licenseType: string;
  licenseRef?: string;
  scenarioId?: string;
}) {
  const form = new FormData();
  files.forEach((file, index) => {
    const filename = file instanceof File ? file.name : `source-${index + 1}`;
    form.append('files', file, filename);
  });
  form.append('title', title);
  form.append('license_type', licenseType || DEFAULT_LICENSE_TYPE);
  if (licenseRef) form.append('license_ref', licenseRef);
  if (scenarioId) form.append('scenario_id', scenarioId);
  return form;
}

function getScenarioDisplayStatus(scenario?: ScenarioSummary) {
  if (scenario?.publish_status === 'published') return 'published';
  return scenario?.import_status || scenario?.status || scenario?.publish_status || 'draft';
}

export function normalizeScenarioImportResult(
  result: Record<string, any>,
): Record<string, any> {
  const jobId = result.job_id
    || (Array.isArray(result.job_ids) ? result.job_ids[0] : '');
  return { ...result, job_id: jobId || undefined };
}

export function recoverScenarioImportResult(
  scenario: ScenarioSummary,
): Record<string, any> | null {
  if (
    scenario.import_status !== 'awaiting_provider'
    && !scenario.latest_import_job_retryable
    || !scenario.latest_import_job_id
  ) return null;
  return normalizeScenarioImportResult({
    scenario_id: scenario.scenario_id,
    status: scenario.latest_import_job_status || scenario.import_status,
    job_id: scenario.latest_import_job_id,
    retryable: scenario.latest_import_job_retryable === true,
  });
}

export function chooseScenarioImportResult(
  current: Record<string, any> | null,
  recovery: Record<string, any> | null,
  selectedScenarioId: string,
): Record<string, any> | null {
  if (!recovery) {
    if (
      current?.scenario_id === selectedScenarioId
      && (current.scenario_version_id || current.status === 'draft_ready')
    ) return current;
    return null;
  }
  if (
    current
    && current.scenario_id === recovery.scenario_id
    && (current.scenario_version_id || current.status === 'draft_ready')
  ) return current;
  return recovery;
}

function sanitizeCitationText(value: unknown) {
  if (typeof value !== 'string') return '';
  return sanitizeAdminScenarioError(value);
}

function summarizeQualityIssues(report?: Record<string, any>) {
  if (!report) return [] as string[];
  if (Array.isArray(report.issues)) {
    return report.issues
      .map((item: any) => {
        if (typeof item === 'string') return item;
        if (item && typeof item === 'object') return String(item.message || item.title || item.code || '');
        return '';
      })
      .filter(Boolean);
  }
  if (typeof report.summary === 'string' && report.summary) return [report.summary];
  return [];
}

function summarizePrepStats(prepPackage?: Record<string, any>) {
  return {
    sceneCount: Array.isArray(prepPackage?.scenes) ? prepPackage!.scenes.length : 0,
    npcCount: Array.isArray(prepPackage?.npcs) ? prepPackage!.npcs.length : 0,
    clueCount: Array.isArray(prepPackage?.clues) ? prepPackage!.clues.length : 0,
  };
}

function getDefaultImportTitle(files: File[]) {
  if (files.length === 1) return files[0].name.replace(/\.[^.]+$/, '');
  return files.length > 1 ? `多模态剧本导入 ${new Date().toLocaleDateString('zh-CN')}` : '';
}

function formatDateText(value?: string) {
  return value || '—';
}

function mergeVersionDetail(
  versions: ScenarioVersion[],
  detail: Record<string, any> | null,
  scenarioVersionId: string,
): ScenarioVersionDetail | null {
  if (!detail) return null;
  const matched = versions.find((version) => version.scenario_version_id === scenarioVersionId);
  return { ...matched, ...detail, scenario_version_id: scenarioVersionId };
}

type ScenarioVersionInspectorProps = {
  scenarioTitle: string;
  versionDetail: ScenarioVersionDetail | null;
  publishChecked: boolean;
  publishNotes: string;
  publishing: boolean;
  onPublishCheckedChange: (checked: boolean) => void;
  onPublishNotesChange: (value: string) => void;
  onPublish: () => void;
};

export function ScenarioVersionInspector({
  scenarioTitle,
  versionDetail,
  publishChecked,
  publishNotes,
  publishing,
  onPublishCheckedChange,
  onPublishNotesChange,
  onPublish,
}: ScenarioVersionInspectorProps) {
  if (!versionDetail) {
    return <div className="bh-muted-box">选择版本后可查看质量报告与 AI 备团摘要。</div>;
  }

  const status = getScenarioStatusMeta(versionDetail.status);
  const qualityIssues = summarizeQualityIssues(versionDetail.quality_report);
  const prepPackage = versionDetail.prep_package || {};
  const stats = summarizePrepStats(prepPackage);
  const citations = Array.isArray(prepPackage.citations) ? prepPackage.citations : [];
  const recommendedSkills = Array.isArray(prepPackage.recommended_skills) ? prepPackage.recommended_skills : [];
  const qualityLevel = typeof versionDetail.quality_report?.level === 'string'
    ? versionDetail.quality_report.level
    : 'unknown';
  const publishGate = getScenarioPublishGate(qualityLevel);
  const soloAdventure = prepPackage.solo_adventure || {};

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      <div className="bh-panel" style={{ padding: 12 }}>
        <span className="bh-eyebrow">{status.eyebrow}</span>
        <h3 style={{ marginBottom: 6 }}>{scenarioTitle || '未命名剧本'}</h3>
        <div className="bh-skill-row" style={{ padding: '4px 0' }}>
          <span>版本 #{versionDetail.version_number || '?'}</span>
          <span style={{ color: status.color, fontWeight: 800 }}>{status.label} ({versionDetail.status || 'draft'})</span>
        </div>
        <div className="bh-skill-row" style={{ padding: '4px 0' }}>
          <span>创建时间</span>
          <span>{formatDateText(versionDetail.created_at)}</span>
        </div>
        <div className="bh-skill-row" style={{ padding: '4px 0' }}>
          <span>发布时间</span>
          <span>{formatDateText(versionDetail.published_at)}</span>
        </div>
        <div className="bh-skill-row" style={{ padding: '4px 0' }}>
          <span>质量评级</span>
          <span>{qualityLevel}</span>
        </div>
      </div>

      {soloAdventure.node_count ? (
        <div className="bh-panel" style={{ padding: 12 }}>
          <span className="bh-eyebrow">SOLO ORIGINAL</span>
          <strong>编号单人冒险完整性</strong>
          <div className="bh-skill-row" style={{ padding: '6px 0', marginTop: 8 }}>
            <span>根节点 / 节点 / 跳转</span>
            <span>{soloAdventure.root_node_id || '—'} / {soloAdventure.node_count} / {soloAdventure.edge_count}</span>
          </div>
          <div className="bh-skill-row" style={{ padding: '6px 0' }}>
            <span>发布门禁</span>
            <span style={{ color: soloAdventure.is_valid ? 'var(--bh-green)' : 'var(--bh-red)' }}>
              {soloAdventure.is_valid ? '结构有效' : '阻止发布'}
            </span>
          </div>
        </div>
      ) : null}

      <div className="bh-panel" style={{ padding: 12 }}>
        <span className="bh-eyebrow">QUALITY</span>
        <strong>质量报告</strong>
        {typeof versionDetail.quality_report?.summary === 'string' && versionDetail.quality_report.summary && (
          <p style={{ marginTop: 8 }}>{versionDetail.quality_report.summary}</p>
        )}
        {qualityIssues.length > 0 ? (
          <div className="bh-preset-list" style={{ marginTop: 8 }}>
            {qualityIssues.map((issue) => (
              <div key={issue} className="bh-skill-row" style={{ padding: '6px 0' }}>
                <span style={{ color: 'var(--bh-red)' }}>风险</span>
                <span>{issue}</span>
              </div>
            ))}
          </div>
        ) : (
          <div className="bh-muted-box" style={{ marginTop: 8 }}>暂无额外风险项。</div>
        )}
      </div>

      <div className="bh-panel" style={{ padding: 12 }}>
        <span className="bh-eyebrow">AI PREP</span>
        <strong>AI 备团包摘要</strong>
        <p style={{ marginTop: 8 }}>{prepPackage.summary || '暂无摘要。'}</p>
        <div className="bh-grid-links" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', marginTop: 8 }}>
          <div className="bh-link-card" style={{ minHeight: 80 }}>
            <span className="bh-eyebrow">SCENES</span>
            <strong>{stats.sceneCount}</strong>
            <span>场景数</span>
          </div>
          <div className="bh-link-card" style={{ minHeight: 80 }}>
            <span className="bh-eyebrow">NPCS</span>
            <strong>{stats.npcCount}</strong>
            <span>NPC 数</span>
          </div>
          <div className="bh-link-card" style={{ minHeight: 80 }}>
            <span className="bh-eyebrow">CLUES</span>
            <strong>{stats.clueCount}</strong>
            <span>线索数</span>
          </div>
        </div>
        {recommendedSkills.length > 0 && (
          <div style={{ marginTop: 10 }}>
            <strong>推荐技能</strong>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
              {recommendedSkills.map((skill) => (
                <span key={String(skill)} className="bh-button" style={{ minHeight: 28, padding: '2px 8px', fontSize: 11 }}>
                  {String(skill)}
                </span>
              ))}
            </div>
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          <strong>引用依据</strong>
          {citations.length > 0 ? (
            <div className="bh-preset-list" style={{ marginTop: 8 }}>
              {citations.map((citation: any, index: number) => (
                <div key={`${citation.source_ref || 'citation'}-${index}`} className="bh-preset-card" style={{ textAlign: 'left' }}>
                  <strong>{sanitizeCitationText(citation.source_ref) || `引用 ${index + 1}`}</strong>
                  <span>{sanitizeCitationText(citation.excerpt) || '无节选'}</span>
                </div>
              ))}
            </div>
          ) : (
            <div className="bh-muted-box" style={{ marginTop: 8 }}>暂无 citation。</div>
          )}
        </div>
      </div>

      {(versionDetail.status === 'draft' || versionDetail.status === 'draft_review') && publishGate.blocked && (
        <div className="bh-panel" style={{ padding: 12, borderColor: 'var(--bh-red)' }}>
          <span className="bh-eyebrow">PUBLISH BLOCKED</span>
          <strong>存在阻塞质量问题</strong>
          <p style={{ marginTop: 8 }}>请先修复质量报告中的错误、重新编译并复核。管理员不能绕过此门禁。</p>
        </div>
      )}

      {(versionDetail.status === 'draft' || versionDetail.status === 'draft_review') && !publishGate.blocked && (
        <div className="bh-panel" style={{ padding: 12, borderColor: 'var(--bh-yellow)' }}>
          <span className="bh-eyebrow">PUBLISH</span>
          <strong>确认后发布</strong>
          <p style={{ marginTop: 8 }}>发布会将此版本设为可开房版本，请先核对风险与引用。</p>
          <textarea
            className="bh-input"
            value={publishNotes}
            onChange={(e) => onPublishNotesChange(e.target.value)}
            placeholder="填写复核说明（可选）"
            style={{ minHeight: 96, marginTop: 8, resize: 'vertical' }}
          />
          <label style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 10, fontSize: 12, fontWeight: 700 }}>
            <input type="checkbox" checked={publishChecked} onChange={(e) => onPublishCheckedChange(e.target.checked)} />
            我已确认该版本可发布
          </label>
          <button className="bh-button bh-button--yellow" style={{ marginTop: 10 }} disabled={!publishChecked || publishing} onClick={onPublish}>
            {publishing ? '发布中...' : '确认后发布'}
          </button>
        </div>
      )}
    </div>
  );
}

type ScenarioImportStatusCardProps = {
  importResult: Record<string, any> | null;
  retrying: boolean;
  retryError: string;
  onRetry: () => void;
};

export function ScenarioImportStatusCard({
  importResult,
  retrying,
  retryError,
  onRetry,
}: ScenarioImportStatusCardProps) {
  if (!importResult) return null;

  const status = getScenarioStatusMeta(importResult.status);
  const canRetry = !!importResult.job_id
    && (importResult.status === 'awaiting_provider' || importResult.retryable === true);

  return (
    <div className="bh-muted-box" style={{ marginTop: 8 }}>
      <strong>最近导入</strong>
      <div style={{ marginTop: 4 }}>scenario_id: {importResult.scenario_id || '—'}</div>
      <div>scenario_version_id: {importResult.scenario_version_id || '—'}</div>
      <div>job_id: {importResult.job_id || '—'}</div>
      <div style={{ color: status.color }}>status: {status.label} ({importResult.status || 'draft'})</div>
      {canRetry && (
        <button className="bh-button bh-button--yellow" style={{ marginTop: 8 }} onClick={onRetry} disabled={retrying}>
          {retrying ? '重试中...' : '重试识别'}
        </button>
      )}
      {retryError && <div style={{ color: 'var(--bh-red)', marginTop: 8 }}>{sanitizeAdminScenarioError(retryError)}</div>}
    </div>
  );
}

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

  const accountRaw = getSlotValue('account');
  const account = accountRaw ? JSON.parse(accountRaw) : {};

  return (
    <div className="bh-page" style={{ padding: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, padding: '16px 24px', borderBottom: '6px solid var(--bh-black)', background: 'var(--bh-paper)' }}>
        <div className="bh-logo-mark" style={{ width: 44, height: 44, fontSize: 20 }}>AK</div>
        <strong style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontSize: 22 }}>ADMIN</strong>
        <span style={{ flex: 1 }} />
        <span style={{ fontWeight: 800, fontSize: 13 }}>{account.display_name || account.username}</span>
        <button className="bh-button" style={{ minHeight: 36, padding: '6px 12px', fontSize: 12 }} onClick={() => { setSlotValue('account_token', ''); setSlotValue('account', ''); window.location.href = '/'; }}>登出</button>
      </div>
      <div style={{ display: 'flex', gap: 0, borderBottom: '4px solid var(--bh-black)' }}>
        {ADMIN_TABS.map((t) => (
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
        {tab === 'systemTools' && <SystemToolsPanel />}
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
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deleteMessage, setDeleteMessage] = useState('');
  const [deleting, setDeleting] = useState(false);

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

  const toggleSelected = (id: string, checked: boolean) => {
    setSelectedIds((prev) => (checked ? [...prev.filter((value) => value !== id), id] : prev.filter((value) => value !== id)));
    setDeleteMessage('');
  };

  const isChecked = (id: string) => selectedIds.includes(id);

  const deleteRoom = async (id: string) => {
    if (!window.confirm('确定要删除该房间吗？')) return;
    setDeleting(true);
    try {
      await api(`/api/admin/rooms/${id}`, { method: 'DELETE' });
      if (selected === id) {
        setSelected('');
        setDetail(null);
      }
      setSelectedIds((prev) => prev.filter((roomId) => roomId !== id));
      setDeleteMessage(`已删除房间 ${id}`);
      load();
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  const batchDeleteRooms = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`确定要删除 ${selectedIds.length} 个房间吗？`)) return;
    setDeleting(true);
    setDeleteMessage('');
    try {
      const result = await api('/api/admin/rooms/batch-delete', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedIds }),
      }) as Record<string, any>;
      const deletedIds = Array.isArray(result.deleted_ids) ? result.deleted_ids : [];
      const errors = Array.isArray(result.errors) ? result.errors : [];
      setSelectedIds((prev) => prev.filter((id) => !deletedIds.includes(id)));
      if (deletedIds.includes(selected)) {
        setSelected('');
        setDetail(null);
      }
      if (errors.length > 0) {
        const failed = errors.map((item: any) => `${item.id}:${item.error}`).join('；');
        setDeleteMessage(`已删除 ${deletedIds.length} 个，失败 ${errors.length} 个：${failed}`);
      } else {
        setDeleteMessage(`已删除 ${deletedIds.length} 个房间`);
      }
      await load();
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
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
      const token = getSlotValue('account_token') || '';
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
          {selectedIds.length > 0 && (
            <button className="bh-button bh-button--red" onClick={batchDeleteRooms} disabled={deleting || loading}>
              批量删除（{selectedIds.length}）
            </button>
          )}
          <button className="bh-button bh-button--yellow" onClick={() => { setShowCreate(!showCreate); if (!showCreate) { api(SCENARIO_ROOM_OPTIONS_ENDPOINT).then(setScenarioList); api('/api/admin/accounts').then(setAccountList); } }}>{showCreate ? '取消' : '新建房间'}</button>
          <button className="bh-button" onClick={load} disabled={loading}>刷新</button>
        </div>
      </div>
      {deleteMessage && <div className="bh-muted-box" style={{ marginTop: 8, color: deleting ? 'var(--bh-muted)' : 'var(--bh-blue)' }}>{deleteMessage}</div>}

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
            <div
              key={r.room_id}
              className={`bh-preset-card ${selected === r.room_id ? 'bh-preset-card--selected' : ''}`}
              style={{ position: 'relative', cursor: 'pointer' }}
              onClick={() => showDetail(r.room_id)}
            >
              <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, position: 'absolute', left: 10, top: 10 }}>
                <input
                  type="checkbox"
                  checked={isChecked(r.room_id)}
                  onClick={(event) => event.stopPropagation()}
                  onChange={(event) => toggleSelected(r.room_id, event.target.checked)}
                />
                <span style={{ fontSize: 11 }}>选择</span>
              </label>
              <strong style={{ marginLeft: 56 }}>{r.room_id}</strong>
              <span>{r.scenario_title || '无剧本'}</span>
              <small style={{ color: statusColors[r.status] || 'var(--bh-muted)' }}>{r.status}</small>
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                <button
                  className="bh-button bh-button--red"
                  style={{ padding: '2px 8px', fontSize: 11 }}
                  onClick={(event) => {
                    event.stopPropagation();
                    void deleteRoom(r.room_id);
                  }}
                  disabled={deleting}
                >
                  删除
                </button>
              </div>
            </div>
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

// ── AI Providers ──

const EMPTY_AI_PROVIDER_DRAFT: AiProviderDraft = {
  name: '',
  apiBaseUrl: '',
  protocol: 'responses',
  model: 'gpt-5.4',
  apiKey: '',
  supportsImage: false,
};

const providerTestLabels: Record<string, string> = {
  untested: '未测试',
  passed: '测试通过',
  failed: '测试失败',
  key_unavailable: '需重新输入 Key',
};

const providerErrorLabels: Record<string, string> = {
  auth_failed: '认证失败，请检查 API Key。',
  model_not_found: '模型不存在或当前账号无权访问。',
  timeout: '连接超时。',
  rate_limited: '请求过于频繁，请稍后重试。',
  invalid_response: '上游响应格式无效。',
  text_unsupported: '当前配置不支持文本请求。',
  image_unsupported: '当前配置不支持图片请求。',
  key_unavailable: '密钥无法解密，请重新输入 API Key。',
  provider_test_required: '请先保存并通过连接测试。',
  api_key_required: '新配置必须填写 API Key。',
  unsafe_api_base_url: 'API 地址被安全策略拒绝。',
  api_host_unresolved: 'API 主机无法解析。',
};

function draftFromProvider(provider?: AiProviderConfig): AiProviderDraft {
  if (!provider) return { ...EMPTY_AI_PROVIDER_DRAFT };
  return {
    name: provider.name,
    apiBaseUrl: provider.api_base_url,
    protocol: provider.protocol,
    model: provider.model,
    apiKey: '',
    supportsImage: provider.supports_image,
  };
}

function providerErrorText(error: unknown) {
  const code = coerceErrorMessage(error);
  return providerErrorLabels[code] || '操作失败，请检查配置后重试。';
}

export function AiProviderPanel({
  initialProviders,
}: {
  initialProviders?: AiProviderConfig[];
} = {}) {
  const initialProvider = initialProviders?.[0];
  const [providers, setProviders] = useState<AiProviderConfig[]>(initialProviders || []);
  const [selectedId, setSelectedId] = useState(initialProvider?.provider_config_id || '');
  const [draft, setDraft] = useState<AiProviderDraft>(draftFromProvider(initialProvider));
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [probeResult, setProbeResult] = useState<Record<string, any> | null>(null);

  const selectProvider = (provider?: AiProviderConfig) => {
    setSelectedId(provider?.provider_config_id || '');
    setDraft(draftFromProvider(provider));
    setDirty(false);
    setMessage('');
    setError('');
    setProbeResult(null);
  };

  const reload = async (preferredId?: string) => {
    const list = await api(AI_PROVIDER_ENDPOINT) as AiProviderConfig[];
    setProviders(list);
    const target = list.find((provider) => provider.provider_config_id === preferredId)
      || list.find((provider) => provider.provider_config_id === selectedId)
      || list[0];
    selectProvider(target);
    return list;
  };

  useEffect(() => {
    if (initialProviders === undefined) reload().catch((loadError) => setError(providerErrorText(loadError)));
  }, []);

  const selected = providers.find((provider) => provider.provider_config_id === selectedId);

  const updateDraft = <K extends keyof AiProviderDraft>(key: K, value: AiProviderDraft[K]) => {
    setDraft((current) => ({ ...current, [key]: value }));
    setDirty(true);
    setMessage('');
    setProbeResult(null);
  };

  const save = async () => {
    setBusy('save');
    setError('');
    setMessage('');
    try {
      const payload: Record<string, unknown> = {
        name: draft.name.trim(),
        api_base_url: draft.apiBaseUrl.trim(),
        protocol: draft.protocol,
        model: draft.model.trim(),
        supports_image: draft.supportsImage,
      };
      if (draft.apiKey) payload.api_key = draft.apiKey;
      const saved = await api(
        selectedId ? `${AI_PROVIDER_ENDPOINT}/${selectedId}` : AI_PROVIDER_ENDPOINT,
        {
          method: selectedId ? 'PATCH' : 'POST',
          body: JSON.stringify(payload),
        },
      ) as AiProviderConfig;
      await reload(saved.provider_config_id);
      setMessage('已保存。请继续测试连接。');
    } catch (saveError) {
      setError(providerErrorText(saveError));
    } finally {
      setBusy('');
    }
  };

  const testConnection = async () => {
    if (!selectedId) return;
    setBusy('test');
    setError('');
    setMessage('');
    try {
      const result = await api(`${AI_PROVIDER_ENDPOINT}/${selectedId}/test`, { method: 'POST' });
      setProbeResult(result);
      await reload(selectedId);
      setProbeResult(result);
      setMessage(result.ok ? '连接测试通过，可以设为启用。' : '连接测试未通过。');
    } catch (testError) {
      setError(providerErrorText(testError));
    } finally {
      setBusy('');
    }
  };

  const activate = async () => {
    if (!selectedId) return;
    setBusy('activate');
    setError('');
    setMessage('');
    try {
      await api(`${AI_PROVIDER_ENDPOINT}/${selectedId}/activate`, { method: 'POST' });
      await reload(selectedId);
      setMessage('已设为全局活动配置，后续 AI 调用立即生效。');
    } catch (activateError) {
      setError(providerErrorText(activateError));
    } finally {
      setBusy('');
    }
  };

  const remove = async () => {
    if (!selectedId || !selected) return;
    if (selected.is_active && !window.confirm('删除当前活动配置后将恢复旧供应商链，确认删除？')) return;
    setBusy('delete');
    setError('');
    setMessage('');
    try {
      await api(`${AI_PROVIDER_ENDPOINT}/${selectedId}`, { method: 'DELETE' });
      await reload();
      setMessage(selected.is_active ? '活动配置已删除，已恢复旧供应商链。' : '配置已删除。');
    } catch (deleteError) {
      setError(providerErrorText(deleteError));
    } finally {
      setBusy('');
    }
  };

  const canSave = !!draft.name.trim()
    && !!draft.apiBaseUrl.trim()
    && !!draft.model.trim()
    && (!!selectedId || !!draft.apiKey);
  const canTest = !!selectedId && !dirty;
  const canActivate = canTest && selected?.test_status === 'passed' && !selected.is_active;

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div>
          <span className="bh-eyebrow">AI PROVIDERS</span>
          <h2 className="bh-panel-title">API配置</h2>
        </div>
        <button className="bh-button bh-button--yellow" onClick={() => selectProvider()}>新增配置</button>
      </div>
      <p style={{ marginTop: 4 }}>按“保存 → 测试连接 → 设为启用”的顺序操作；全局仅启用一套配置。</p>

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 0.8fr) minmax(360px, 1.5fr)', gap: 16, marginTop: 16 }}>
        <div className="bh-preset-list">
          {providers.length === 0 && <div className="bh-muted-box">尚未保存供应商配置。</div>}
          {providers.map((provider) => (
            <button
              key={provider.provider_config_id}
              className={`bh-preset-card ${selectedId === provider.provider_config_id ? 'bh-preset-card--selected' : ''}`}
              onClick={() => selectProvider(provider)}
              style={{ textAlign: 'left' }}
            >
              <strong>{provider.name}</strong>
              <span>{provider.protocol} · {provider.model}</span>
              <small>{provider.key_mask} · {providerTestLabels[provider.test_status] || provider.test_status}</small>
              <small>{provider.is_active ? '当前活动配置' : '未启用'}{provider.last_test_latency_ms !== null ? ` · ${provider.last_test_latency_ms}ms` : ''}</small>
            </button>
          ))}
        </div>

        <div className="bh-panel" style={{ padding: 16 }}>
          <span className="bh-eyebrow">{selectedId ? 'EDIT' : 'NEW'}</span>
          <h3>{selectedId ? '编辑供应商' : '新增供应商'}</h3>
          <div style={{ display: 'grid', gap: 10, marginTop: 12 }}>
            <label>
              <strong>配置名称</strong>
              <input className="bh-input" value={draft.name} onChange={(event) => updateDraft('name', event.target.value)} placeholder="例如：公司网关" />
            </label>
            <label>
              <strong>API Base URL</strong>
              <input className="bh-input" value={draft.apiBaseUrl} onChange={(event) => updateDraft('apiBaseUrl', event.target.value)} placeholder="https://api.example.com/v1" autoComplete="off" />
            </label>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
              <label>
                <strong>协议</strong>
                <select className="bh-input" value={draft.protocol} onChange={(event) => updateDraft('protocol', event.target.value as AiProviderDraft['protocol'])}>
                  <option value="responses">Responses</option>
                  <option value="chat_completions">Chat Completions</option>
                </select>
              </label>
              <label>
                <strong>模型</strong>
                <input className="bh-input" value={draft.model} onChange={(event) => updateDraft('model', event.target.value)} />
              </label>
            </div>
            <label>
              <strong>API Key</strong>
              <input
                className="bh-input"
                type="password"
                value={draft.apiKey}
                onChange={(event) => updateDraft('apiKey', event.target.value)}
                placeholder={selected?.has_api_key ? `留空则保留 ${selected.key_mask}` : '新配置必须填写'}
                autoComplete="new-password"
              />
            </label>
            <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontWeight: 700 }}>
              <input type="checkbox" checked={draft.supportsImage} onChange={(event) => updateDraft('supportsImage', event.target.checked)} />
              支持图片理解与生成预览
            </label>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 16 }}>
            <button className="bh-button bh-button--yellow" onClick={save} disabled={!canSave || !!busy}>{busy === 'save' ? '保存中...' : '保存'}</button>
            <button className="bh-button" onClick={testConnection} disabled={!canTest || !!busy}>{busy === 'test' ? '测试中...' : '测试连接'}</button>
            <button className="bh-button" onClick={activate} disabled={!canActivate || !!busy}>{busy === 'activate' ? '启用中...' : '设为启用'}</button>
            {selectedId && <button className="bh-button bh-button--red" onClick={remove} disabled={!!busy}>{busy === 'delete' ? '删除中...' : '删除'}</button>}
          </div>

          {dirty && selectedId && <div className="bh-muted-box" style={{ marginTop: 10 }}>配置已修改，请先保存；保存后需要重新测试。</div>}
          {probeResult && (
            <div className="bh-muted-box" style={{ marginTop: 10 }}>
              <strong>{probeResult.ok ? '测试通过' : '测试失败'} · {probeResult.latency_ms ?? 0}ms</strong>
              <div>文本：{probeResult.text?.ok ? '通过' : providerErrorLabels[probeResult.text?.error_code] || '失败'}</div>
              {probeResult.image?.required && <div>图片：{probeResult.image?.ok ? '通过' : providerErrorLabels[probeResult.image?.error_code] || '失败'}</div>}
            </div>
          )}
          {message && <div className="bh-muted-box" style={{ color: 'var(--bh-blue)', marginTop: 10 }}>{message}</div>}
          {error && <div className="bh-muted-box" style={{ color: 'var(--bh-red)', marginTop: 10 }}>{error}</div>}
        </div>
      </div>
    </section>
  );
}

type ResetBackup = {
  backup_id: string;
  sha256: string;
  counts: Record<string, number>;
  downloaded_at?: string | null;
};

function SystemToolsPanel() {
  return (
    <section>
      <span className="bh-eyebrow">SYSTEM TOOLS</span>
      <h2 className="bh-panel-title">系统工具</h2>
      <p className="bh-panel-desc">配置 AI、验收 RAG、执行浏览器检查，并在严格备份门禁下重置测试数据。</p>
      <div className="bh-grid-links" style={{ margin: '16px 0' }}>
        <a className="bh-link-card" href="/rag-test">
          <span className="bh-eyebrow">RAG</span>
          <strong>规则检索验收台</strong>
          <span>使用黄金问题核对命中片段与 citation。</span>
        </a>
        <a className="bh-link-card" href="/admin/acceptance">
          <span className="bh-eyebrow">BROWSER</span>
          <strong>体验验收中心</strong>
          <span>从测试入口按角色完成手工验证。</span>
        </a>
      </div>
      <div className="bh-panel" style={{ marginBottom: 16 }}>
        <AiProviderPanel />
      </div>
      <ResetDataPanel />
    </section>
  );
}

function ResetDataPanel() {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [backup, setBackup] = useState<ResetBackup | null>(null);
  const [downloaded, setDownloaded] = useState(false);
  const [verified, setVerified] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const loadPreflight = async () => {
    const data = await api('/api/admin/reset/preflight') as { counts: Record<string, number> };
    setCounts(data.counts || {});
  };

  useEffect(() => {
    loadPreflight().catch(() => setError('无法读取重置预检。'));
  }, []);

  const createBackup = async () => {
    setBusy('backup');
    setError('');
    setMessage('');
    try {
      const created = await api('/api/admin/reset/backups', { method: 'POST' }) as ResetBackup;
      setBackup(created);
      setDownloaded(false);
      setVerified(false);
      setAcknowledged(false);
      setMessage('备份已生成。请下载、校验后再解锁重置。');
    } catch (caught) {
      setError(coerceErrorMessage(caught));
    } finally {
      setBusy('');
    }
  };

  const downloadBackup = async () => {
    if (!backup) return;
    setBusy('download');
    setError('');
    try {
      const token = getSlotValue('account_token') || '';
      const response = await fetch(`/api/admin/reset/backups/${encodeURIComponent(backup.backup_id)}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) throw new Error('备份下载失败');
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = `aikeeper-global-reset-${backup.backup_id}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
      setDownloaded(true);
      setMessage('备份已下载；下一步校验 SHA-256 和压缩包结构。');
    } catch (caught) {
      setError(coerceErrorMessage(caught));
    } finally {
      setBusy('');
    }
  };

  const verifyBackup = async () => {
    if (!backup) return;
    setBusy('verify');
    setError('');
    try {
      const result = await api(`/api/admin/reset/backups/${encodeURIComponent(backup.backup_id)}/verify`) as { valid?: boolean } & ResetBackup;
      setVerified(result.valid === true);
      setBackup(result);
      setMessage(result.valid ? 'SHA-256、清单和房间包均已校验。' : '备份未通过校验。');
    } catch (caught) {
      setVerified(false);
      setError(coerceErrorMessage(caught));
    } finally {
      setBusy('');
    }
  };

  const executeReset = async () => {
    if (!backup || !canExecuteGlobalReset({ backupId: backup.backup_id, downloaded, verified, acknowledged })) return;
    if (!window.confirm('将删除所有房间、角色与战役记录，账号和内容库会保留。确认继续？')) return;
    setBusy('reset');
    setError('');
    try {
      const result = await api('/api/admin/reset/execute', {
        method: 'POST',
        body: JSON.stringify({ backup_id: backup.backup_id, confirm_download: true }),
      }) as { deleted: Record<string, number> };
      await loadPreflight();
      setMessage(`重置已完成：清理 ${Object.values(result.deleted || {}).reduce((total, value) => total + value, 0)} 条房间相关记录。`);
    } catch (caught) {
      setError(coerceErrorMessage(caught));
    } finally {
      setBusy('');
    }
  };

  const canReset = backup && canExecuteGlobalReset({
    backupId: backup.backup_id,
    downloaded,
    verified,
    acknowledged,
  });

  return (
    <section className="bh-panel" aria-label="全局数据重置">
      <span className="bh-eyebrow">RESET GATE</span>
      <h3 className="bh-panel-title">重置房间与战役数据</h3>
      <p className="bh-panel-desc">保留账号、已发布剧本与内容素材；删除全部房间、角色、行动和战役记录。服务器备份保留 90 天。</p>
      <div className="bh-muted-box">
        预检：{Object.entries(counts).map(([key, value]) => `${key} ${value}`).join(' · ') || '加载中'}
      </div>
      <div className="bh-action-row bh-action-row--responsive" style={{ marginTop: 12 }}>
        <button className="bh-button bh-button--yellow" type="button" onClick={() => void createBackup()} disabled={Boolean(busy)}>
          {busy === 'backup' ? '生成中...' : '1. 生成备份'}
        </button>
        <button className="bh-button" type="button" onClick={() => void downloadBackup()} disabled={!backup || Boolean(busy)}>
          {busy === 'download' ? '下载中...' : '2. 下载备份'}
        </button>
        <button className="bh-button" type="button" onClick={() => void verifyBackup()} disabled={!backup || !downloaded || Boolean(busy)}>
          {busy === 'verify' ? '校验中...' : '3. 校验备份'}
        </button>
      </div>
      {backup && (
        <div className="bh-muted-box" style={{ marginTop: 12 }}>
          <div>备份：{backup.backup_id}</div>
          <div>SHA-256：{backup.sha256}</div>
          <div>下载：{downloaded ? '已确认' : '未确认'} · 校验：{verified ? '通过' : '未通过'}</div>
        </div>
      )}
      <label style={{ display: 'flex', gap: 8, alignItems: 'flex-start', marginTop: 12, fontSize: 13 }}>
        <input type="checkbox" checked={acknowledged} onChange={(event) => setAcknowledged(event.target.checked)} disabled={!verified} />
        我已下载并验证备份，理解重置后旧房间运行状态不再兼容。
      </label>
      <button className="bh-button bh-button--red" type="button" style={{ marginTop: 12 }} onClick={() => void executeReset()} disabled={!canReset || Boolean(busy)}>
        {busy === 'reset' ? '清理中...' : '4. 执行不可逆重置'}
      </button>
      {message && <div className="bh-muted-box" style={{ color: 'var(--bh-blue)', marginTop: 12 }}>{message}</div>}
      {error && <div className="bh-muted-box" style={{ color: 'var(--bh-red)', marginTop: 12 }}>{error}</div>}
    </section>
  );
}

// ── Scenarios ──

type ScenarioMapDraft = {
  mapId: string;
  generatedBy: string;
  status: 'draft' | 'confirmed';
  mapType: 'graph' | 'image' | 'hybrid';
  baseAsset: Record<string, unknown>;
  nodes: Array<Record<string, unknown>>;
  edges: Array<Record<string, unknown>>;
  regions: Array<Record<string, unknown>>;
  paths: Array<Record<string, unknown>>;
};

export type ScenarioAssetSummary = {
  asset_id: string;
  original_name: string;
  mime_type: string;
};

export function buildScenarioMapGenerateEndpoint(
  scenarioId: string,
  scenarioVersionId: string,
): string {
  const base = `/api/admin/scenarios/${encodeURIComponent(scenarioId)}/map/generate`;
  return scenarioVersionId
    ? `${base}?scenario_version_id=${encodeURIComponent(scenarioVersionId)}`
    : base;
}

export function MapBaseAssetControl({
  assets,
  disabled,
  selectedAssetId,
  onChange,
}: {
  assets: ScenarioAssetSummary[];
  disabled: boolean;
  selectedAssetId: string;
  onChange: (assetId: string) => void;
}) {
  const imageAssets = assets.filter((asset) => asset.mime_type.startsWith('image/'));
  return (
    <label style={{ display: 'grid', gap: 4, fontSize: 12 }}>
      地图底图
      <select
        aria-label="地图底图"
        className="bh-input"
        disabled={disabled}
        value={selectedAssetId}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">不使用图片底图</option>
        {imageAssets.map((asset) => (
          <option key={asset.asset_id} value={asset.asset_id}>{asset.original_name}</option>
        ))}
      </select>
    </label>
  );
}

export function MapDraftReviewPanel({
  scenarioId,
  scenarioVersionId = '',
  assets = [],
}: {
  scenarioId: string;
  scenarioVersionId?: string;
  assets?: ScenarioAssetSummary[];
}) {
  const [mapDraft, setMapDraft] = useState<ScenarioMapDraft | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [previewUrl, setPreviewUrl] = useState('');

  const loadDraft = async () => {
    if (!scenarioId) return;
    setLoading(true);
    setError('');
    try {
      setMapDraft(await api(`/api/admin/scenarios/${encodeURIComponent(scenarioId)}/map`));
    } catch {
      setMapDraft(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDraft();
  }, [scenarioId]);

  const selectedAssetId = String(mapDraft?.baseAsset?.assetId || '');
  useEffect(() => {
    if (!selectedAssetId) {
      setPreviewUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return '';
      });
      return;
    }
    let active = true;
    fetch(
      `/api/admin/scenarios/${encodeURIComponent(scenarioId)}/assets/${encodeURIComponent(selectedAssetId)}/content`,
      { headers: getAuthHeader() },
    )
      .then((response) => response.ok ? response.blob() : null)
      .then((blob) => {
        if (!blob || !active) return;
        setPreviewUrl((current) => {
          if (current) URL.revokeObjectURL(current);
          return URL.createObjectURL(blob);
        });
      })
      .catch(() => setPreviewUrl(''));
    return () => { active = false; };
  }, [scenarioId, selectedAssetId]);

  const generate = async () => {
    setSaving(true);
    setError('');
    try {
      setMapDraft(await api(buildScenarioMapGenerateEndpoint(scenarioId, scenarioVersionId), { method: 'POST' }));
    } catch (generationError) {
      setError(sanitizeAdminScenarioError(generationError));
    } finally {
      setSaving(false);
    }
  };

  const saveMapType = async (mapType: ScenarioMapDraft['mapType']) => {
    if (!mapDraft || mapDraft.status !== 'draft') return;
    setSaving(true);
    setError('');
    try {
      await api(`/api/admin/scenarios/${encodeURIComponent(scenarioId)}/map`, {
        method: 'PATCH',
        body: JSON.stringify({
          mapType,
          baseAsset: mapDraft.baseAsset,
          nodes: mapDraft.nodes,
          edges: mapDraft.edges,
          regions: mapDraft.regions,
          paths: mapDraft.paths,
        }),
      });
      setMapDraft({ ...mapDraft, mapType });
    } catch (saveError) {
      setError(sanitizeAdminScenarioError(saveError));
    } finally {
      setSaving(false);
    }
  };

  const saveBaseAsset = async (assetId: string) => {
    if (!mapDraft || mapDraft.status !== 'draft') return;
    const mapType = assetId && mapDraft.mapType === 'graph' ? 'hybrid' : mapDraft.mapType;
    const baseAsset = assetId ? { assetId } : {};
    setSaving(true);
    setError('');
    try {
      await api(`/api/admin/scenarios/${encodeURIComponent(scenarioId)}/map`, {
        method: 'PATCH',
        body: JSON.stringify({
          mapType,
          baseAsset,
          nodes: mapDraft.nodes,
          edges: mapDraft.edges,
          regions: mapDraft.regions,
          paths: mapDraft.paths,
        }),
      });
      setMapDraft({ ...mapDraft, mapType, baseAsset });
    } catch (saveError) {
      setError(sanitizeAdminScenarioError(saveError));
    } finally {
      setSaving(false);
    }
  };

  const confirm = async () => {
    if (!mapDraft || mapDraft.status !== 'draft') return;
    setSaving(true);
    setError('');
    try {
      const confirmed = await api(`/api/admin/scenarios/${encodeURIComponent(scenarioId)}/map/confirm`, { method: 'POST' });
      setMapDraft({ ...mapDraft, status: confirmed.status });
    } catch (confirmError) {
      setError(sanitizeAdminScenarioError(confirmError));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bh-panel" style={{ padding: 12, marginTop: 12 }}>
      <span className="bh-eyebrow">MAP PREP</span>
      <strong>地图草稿</strong>
      <p style={{ fontSize: 12, color: 'var(--bh-dim)', marginTop: 6 }}>
        区域与路径仅在备团阶段由管理员审核。
      </p>
      {loading ? <div className="bh-muted-box">加载地图草稿...</div> : mapDraft ? (
        <div style={{ display: 'grid', gap: 8, marginTop: 8 }}>
          <div className="bh-muted-box">
            {mapDraft.status === 'confirmed' ? '已确认' : '待审核'} · {mapDraft.generatedBy} · 节点 {mapDraft.nodes.length} · 区域 {mapDraft.regions.length} · 路径 {mapDraft.paths.length}
          </div>
          <label style={{ display: 'grid', gap: 4, fontSize: 12 }}>
            地图类型
            <select
              className="bh-input"
              value={mapDraft.mapType}
              disabled={saving || mapDraft.status !== 'draft'}
              onChange={(event) => saveMapType(event.target.value as ScenarioMapDraft['mapType'])}
            >
              <option value="graph">节点图</option>
              <option value="image">图片地图</option>
              <option value="hybrid">混合地图</option>
            </select>
          </label>
          <MapBaseAssetControl
            assets={assets}
            disabled={saving || mapDraft.status !== 'draft'}
            selectedAssetId={selectedAssetId}
            onChange={(assetId) => void saveBaseAsset(assetId)}
          />
          {previewUrl && (
            <img
              alt="地图底图预览"
              src={previewUrl}
              style={{ width: '100%', maxHeight: 320, objectFit: 'contain', border: '3px solid var(--bh-black)' }}
            />
          )}
        </div>
      ) : (
        <div className="bh-muted-box" style={{ marginTop: 8 }}>尚未生成地图草稿；可先发布文字场景模式。</div>
      )}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
        <button className="bh-button" type="button" disabled={saving} onClick={generate}>
          {saving ? '处理中...' : '生成地图草稿'}
        </button>
        <button className="bh-button bh-button--yellow" type="button" disabled={saving || mapDraft?.status !== 'draft'} onClick={confirm}>
          确认地图
        </button>
      </div>
      {error && <div className="bh-muted-box" style={{ color: 'var(--bh-red)', marginTop: 8 }}>{error}</div>}
    </div>
  );
}

export type AssetBindingTarget = {
  target_type: 'map' | 'branch_node' | 'scene' | 'item' | 'clue' | 'npc' | 'ending';
  target_key: string;
  label: string;
};

export type ScenarioAssetBinding = {
  binding_id: string;
  asset_id: string;
  original_name: string;
  target_type: AssetBindingTarget['target_type'];
  target_key: string;
  confidence: number;
  evidence: Record<string, unknown>;
  generated_by: string;
  status: 'draft' | 'confirmed' | 'rejected' | 'stale';
};

function AdminAssetThumbnail({
  scenarioId,
  assetId,
  alt,
}: {
  scenarioId: string;
  assetId: string;
  alt: string;
}) {
  const [src, setSrc] = useState('');
  useEffect(() => {
    let active = true;
    fetch(
      `/api/admin/scenarios/${encodeURIComponent(scenarioId)}/assets/${encodeURIComponent(assetId)}/content`,
      { headers: getAuthHeader() },
    )
      .then((response) => response.ok ? response.blob() : null)
      .then((blob) => {
        if (blob && active) setSrc(URL.createObjectURL(blob));
      })
      .catch(() => setSrc(''));
    return () => {
      active = false;
      if (src) URL.revokeObjectURL(src);
    };
  }, [scenarioId, assetId]);
  return (
    <div aria-label={alt} data-asset-id={assetId}>
      {src && <img alt={alt} src={src} style={{ width: '100%', maxHeight: 180, objectFit: 'contain' }} />}
    </div>
  );
}

export function AssetBindingReviewCard({
  binding,
  disabled,
  scenarioId,
  targets,
  onReview,
}: {
  binding: ScenarioAssetBinding;
  disabled: boolean;
  scenarioId: string;
  targets: AssetBindingTarget[];
  onReview: (
    bindingId: string,
    targetType: AssetBindingTarget['target_type'],
    targetKey: string,
    status: ScenarioAssetBinding['status'],
  ) => void;
}) {
  const [selection, setSelection] = useState(
    JSON.stringify([binding.target_type, binding.target_key]),
  );
  const [targetType, targetKey] = JSON.parse(selection) as [AssetBindingTarget['target_type'], string];
  return (
    <article className="bh-muted-box" style={{ display: 'grid', gap: 8 }}>
      <AdminAssetThumbnail
        scenarioId={scenarioId}
        assetId={binding.asset_id}
        alt={`${binding.original_name} 缩略图`}
      />
      <strong>{binding.original_name}</strong>
      <span>
        {binding.status} · {binding.generated_by} · {Math.round(binding.confidence * 100)}%
      </span>
      <select
        aria-label={`${binding.original_name} 绑定目标`}
        className="bh-input"
        disabled={disabled || binding.status === 'confirmed'}
        value={selection}
        onChange={(event) => setSelection(event.target.value)}
      >
        <option value={JSON.stringify(['scene', ''])}>未匹配</option>
        {targets.map((target) => (
          <option
            key={`${target.target_type}:${target.target_key}`}
            value={JSON.stringify([target.target_type, target.target_key])}
          >
            {target.label} · {target.target_type}
          </option>
        ))}
      </select>
      <code>{JSON.stringify(binding.evidence)}</code>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button
          className="bh-button bh-button--yellow"
          disabled={disabled || !targetKey || binding.status === 'confirmed'}
          onClick={() => onReview(binding.binding_id, targetType, targetKey, 'confirmed')}
          type="button"
        >
          确认绑定
        </button>
        <button
          className="bh-button"
          disabled={disabled || binding.status === 'rejected'}
          onClick={() => onReview(binding.binding_id, targetType, targetKey, 'rejected')}
          type="button"
        >
          拒绝
        </button>
      </div>
    </article>
  );
}

export function ScenarioAssetBindingsPanel({
  scenarioId,
  scenarioVersionId,
}: {
  scenarioId: string;
  scenarioVersionId: string;
}) {
  const [bindings, setBindings] = useState<ScenarioAssetBinding[]>([]);
  const [targets, setTargets] = useState<AssetBindingTarget[]>([]);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const endpoint = scenarioId && scenarioVersionId
    ? `/api/admin/scenarios/${encodeURIComponent(scenarioId)}/versions/${encodeURIComponent(scenarioVersionId)}/asset-bindings`
    : '';
  const applyPayload = (payload: { bindings?: ScenarioAssetBinding[]; targets?: AssetBindingTarget[] }) => {
    setBindings(payload.bindings || []);
    setTargets(payload.targets || []);
  };
  const load = async () => {
    if (!endpoint) {
      applyPayload({});
      return;
    }
    try {
      applyPayload(await api(endpoint));
    } catch {
      applyPayload({});
    }
  };
  useEffect(() => { void load(); }, [endpoint]);

  const generate = async () => {
    if (!endpoint) return;
    setSaving(true);
    setError('');
    try {
      applyPayload(await api(`${endpoint}/generate`, { method: 'POST' }));
    } catch (generationError) {
      setError(sanitizeAdminScenarioError(generationError));
    } finally {
      setSaving(false);
    }
  };

  const review = async (
    bindingId: string,
    targetType: AssetBindingTarget['target_type'],
    targetKey: string,
    status: ScenarioAssetBinding['status'],
  ) => {
    if (!endpoint) return;
    setSaving(true);
    setError('');
    try {
      await api(`${endpoint}/${encodeURIComponent(bindingId)}`, {
        method: 'PATCH',
        body: JSON.stringify({ target_type: targetType, target_key: targetKey, status }),
      });
      await load();
    } catch (reviewError) {
      setError(sanitizeAdminScenarioError(reviewError));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bh-panel" style={{ padding: 12, marginTop: 12 }}>
      <span className="bh-eyebrow">ASSET BINDINGS</span>
      <strong>图片素材绑定</strong>
      <p style={{ fontSize: 12, color: 'var(--bh-dim)' }}>
        只有确认后的图片才会出现在对应条目、线索、物品或结局中。
      </p>
      <button
        className="bh-button bh-button--yellow"
        disabled={saving || !endpoint}
        onClick={() => void generate()}
        type="button"
      >
        {saving ? '匹配中...' : '自动匹配素材'}
      </button>
      <div className="bh-preset-list" style={{ marginTop: 8 }}>
        {bindings.map((binding) => (
          <AssetBindingReviewCard
            key={binding.binding_id}
            binding={binding}
            disabled={saving}
            scenarioId={scenarioId}
            targets={targets}
            onReview={review}
          />
        ))}
      </div>
      {error && <div className="bh-muted-box" style={{ color: 'var(--bh-red)' }}>{error}</div>}
    </div>
  );
}

export function ScenariosPanel() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [assets, setAssets] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);
  const [versions, setVersions] = useState<ScenarioVersion[]>([]);
  const [selectedVersionId, setSelectedVersionId] = useState('');
  const [versionDetail, setVersionDetail] = useState<ScenarioVersionDetail | null>(null);
  const [importFiles, setImportFiles] = useState<File[]>([]);
  const [importTitle, setImportTitle] = useState('');
  const [licenseType, setLicenseType] = useState(DEFAULT_LICENSE_TYPE);
  const [licenseRef, setLicenseRef] = useState('');
  const [loadingVersions, setLoadingVersions] = useState(false);
  const [loadingPrep, setLoadingPrep] = useState(false);
  const [versionError, setVersionError] = useState('');
  const [publishChecked, setPublishChecked] = useState(false);
  const [publishNotes, setPublishNotes] = useState('');
  const [publishing, setPublishing] = useState(false);
  const [publishError, setPublishError] = useState('');
  const [publishSuccess, setPublishSuccess] = useState('');
  const [importResult, setImportResult] = useState<Record<string, any> | null>(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState('');
  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState('');
  const [workflowStep, setWorkflowStep] = useState<ScenarioWorkflowStep>('import');
  const [deleteMessage, setDeleteMessage] = useState('');
  const [deleting, setDeleting] = useState(false);

  const loadScenarios = async () => {
    const list = await api('/api/admin/scenarios');
    setScenarios(list);
    const recoverable = (list as ScenarioSummary[])
      .map(recoverScenarioImportResult)
      .find((result) => result !== null);
    if (recoverable) setImportResult((current) => current || recoverable);
    return list as ScenarioSummary[];
  };

  const toggleScenarioSelected = (id: string, checked: boolean) => {
    setSelectedIds((prev) => (checked ? [...prev.filter((value) => value !== id), id] : prev.filter((value) => value !== id)));
    setDeleteMessage('');
  };

  const batchDeleteScenarios = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`确定要删除 ${selectedIds.length} 个剧本吗？`)) return;
    setDeleting(true);
    setDeleteMessage('');
    try {
      const result = await api('/api/admin/scenarios/batch-delete', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedIds }),
      }) as Record<string, any>;
      const deletedIds = Array.isArray(result.deleted_ids) ? result.deleted_ids : [];
      const errors = Array.isArray(result.errors) ? result.errors : [];
      const nextIds = selectedIds.filter((id) => !deletedIds.includes(id));
      setSelectedIds(nextIds);
      if (deletedIds.includes(selectedId)) {
        setSelectedId('');
        setVersionDetail(null);
        setVersions([]);
      }
      await loadScenarios();
      if (nextIds.length === 0 && selectedId && deletedIds.includes(selectedId)) {
        setSelectedId('');
      }
      if (errors.length > 0) {
        const failed = errors.map((item: any) => `${item.id}:${item.error}`).join('；');
        setDeleteMessage(`已删除 ${deletedIds.length} 个，失败 ${errors.length} 个：${failed}`);
      } else {
        setDeleteMessage(`已删除 ${deletedIds.length} 个剧本`);
      }
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  const deleteScenario = async (id: string) => {
    if (!window.confirm('确定要删除该剧本吗？')) return;
    setDeleting(true);
    setDeleteMessage('');
    try {
      await api(`/api/admin/scenarios/${id}`, { method: 'DELETE' });
      if (selectedId === id) {
        setSelectedId('');
        setVersions([]);
        setVersionDetail(null);
      }
      setSelectedIds((prev) => prev.filter((sid) => sid !== id));
      await loadScenarios();
      setDeleteMessage(`已删除剧本 ${id}`);
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  const loadAssets = (sid: string) => {
    api(`/api/admin/scenarios/${sid}/assets`).then(setAssets).catch(() => setAssets([]));
  };

  const loadVersionDetail = async (sid: string, scenarioVersionId: string, versionList = versions) => {
    if (!scenarioVersionId) {
      setSelectedVersionId('');
      setVersionDetail(null);
      return;
    }
    setLoadingPrep(true);
    setVersionError('');
    setPublishError('');
    setPublishSuccess('');
    setPublishChecked(false);
    try {
      const detail = await api(`/api/scenarios/${sid}/versions/${scenarioVersionId}/prep`);
      setSelectedVersionId(scenarioVersionId);
      setVersionDetail(mergeVersionDetail(versionList, detail, scenarioVersionId));
      const matched = versionList.find((version) => version.scenario_version_id === scenarioVersionId);
      const notes = matched?.review_notes;
      if (typeof notes === 'string') setPublishNotes(notes);
      else if (notes && typeof notes === 'object' && typeof notes.notes === 'string') setPublishNotes(notes.notes);
      else setPublishNotes('');
    } catch (error) {
      setVersionDetail(null);
      setVersionError(sanitizeAdminScenarioError(error));
    } finally {
      setLoadingPrep(false);
    }
  };

  const loadVersions = async (sid: string, preferredVersionId?: string) => {
    setLoadingVersions(true);
    setVersionError('');
    try {
      const versionList = (await api(`/api/scenarios/${sid}/versions`)) as ScenarioVersion[];
      setVersions(versionList);
      const targetVersionId = preferredVersionId || versionList[0]?.scenario_version_id || '';
      if (targetVersionId) await loadVersionDetail(sid, targetVersionId, versionList);
      else {
        setSelectedVersionId('');
        setVersionDetail(null);
      }
    } catch (error) {
      setVersions([]);
      setVersionDetail(null);
      setVersionError(sanitizeAdminScenarioError(error));
    } finally {
      setLoadingVersions(false);
    }
  };

  const selectScenario = async (sid: string, preferredVersionId?: string) => {
    setSelectedId(sid);
    const selectedScenario = scenarios.find((scenario) => scenario.scenario_id === sid);
    const recovery = selectedScenario ? recoverScenarioImportResult(selectedScenario) : null;
    if (recovery) {
      setImportResult((current) => chooseScenarioImportResult(current, recovery, sid));
    } else setImportResult((current) => chooseScenarioImportResult(current, null, sid));
    loadAssets(sid);
    await loadVersions(sid, preferredVersionId);
  };

  useEffect(() => {
    loadScenarios()
      .then((list) => {
        if (list[0]) selectScenario(list[0].scenario_id);
      })
      .catch(() => {});
  }, []);

  const uploadAsset = async (sid: string, file: File) => {
    setUploading(true);
    const form = new FormData();
    form.append('file', file);
    try {
      await fetch(`/api/admin/scenarios/${sid}/assets`, { method: 'POST', headers: getAuthHeader(), body: form });
      loadAssets(sid);
    } catch { /* ignore */ }
    setUploading(false);
  };

  const deleteAsset = async (sid: string, aid: string) => {
    await api(`/api/admin/scenarios/${sid}/assets/${aid}`, { method: 'DELETE' });
    loadAssets(sid);
  };

  const handleImport = async () => {
    if (importFiles.length === 0) {
      setImportError('请至少选择一个源文件。');
      return;
    }
    setImporting(true);
    setImportError('');
    setRetryError('');
    try {
      const form = buildScenarioImportFormData({
        files: importFiles,
        title: importTitle.trim() || getDefaultImportTitle(importFiles),
        licenseType,
        licenseRef: licenseRef.trim(),
      });
      const res = await fetch(SCENARIO_IMPORT_ENDPOINT, {
        method: 'POST',
        headers: getAuthHeader(),
        body: form,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || '导入失败，请检查文件格式与授权信息。');
      }
      const result = normalizeScenarioImportResult(await res.json());
      setImportResult(result);
      const refreshed = await loadScenarios();
      if (result.scenario_id) await selectScenario(result.scenario_id, result.scenario_version_id);
      else if (refreshed[0]) await selectScenario(refreshed[0].scenario_id);
      setImportFiles([]);
      setImportTitle('');
      setLicenseType(DEFAULT_LICENSE_TYPE);
      setLicenseRef('');
    } catch (error) {
      setImportError(sanitizeAdminScenarioError(error));
    } finally {
      setImporting(false);
    }
  };

  const retryImportRecognition = async () => {
    const jobId = importResult?.job_id;
    if (!jobId) return;
    setRetrying(true);
    setRetryError('');
    try {
      const res = await fetch(`/api/scenarios/import-jobs/${jobId}/retry`, {
        method: 'POST',
        headers: getAuthHeader(),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || '重试识别失败，请稍后再试。');
      }
      const result = normalizeScenarioImportResult(await res.json());
      const mergedResult = normalizeScenarioImportResult({ ...importResult, ...result });
      setImportResult(mergedResult);
      const refreshed = await loadScenarios();
      if (mergedResult.scenario_id && (mergedResult.scenario_version_id || mergedResult.status === 'draft_ready')) {
        await selectScenario(mergedResult.scenario_id, mergedResult.scenario_version_id);
      } else if (!selectedId && refreshed[0]) {
        await selectScenario(refreshed[0].scenario_id);
      }
    } catch (error) {
      setRetryError(sanitizeAdminScenarioError(error));
    } finally {
      setRetrying(false);
    }
  };

  const publishVersion = async () => {
    if (!selectedId || !selectedVersionId) return;
    setPublishing(true);
    setPublishError('');
    setPublishSuccess('');
    try {
      await api(`/api/scenarios/${selectedId}/versions/${selectedVersionId}/publish`, {
        method: 'POST',
        body: JSON.stringify({ confirm: true, review_notes: publishNotes.trim() }),
      });
      setPublishChecked(false);
      await loadScenarios();
      await loadVersions(selectedId, selectedVersionId);
      setPublishSuccess('版本已发布。');
    } catch (error) {
      setPublishError(sanitizeAdminScenarioError(error));
    } finally {
      setPublishing(false);
    }
  };

  const selectedScenario = scenarios.find((scenario) => scenario.scenario_id === selectedId);
  const selectedScenarioStatus = getScenarioStatusMeta(getScenarioDisplayStatus(selectedScenario));

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <h2 className="bh-panel-title">剧本 & 素材</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {selectedIds.length > 0 && (
            <button className="bh-button bh-button--red" onClick={batchDeleteScenarios} disabled={deleting}>
              批量删除（{selectedIds.length}）
            </button>
          )}
          <button className="bh-button" onClick={() => { loadScenarios().then((list) => { if (!selectedId && list[0]) selectScenario(list[0].scenario_id); }); }}>刷新</button>
        </div>
      </div>
      {deleteMessage && <div className="bh-muted-box" style={{ marginTop: 8 }}>{deleteMessage}</div>}

      <div className="bh-source-toggle" style={{ marginTop: 12 }} aria-label="剧本导入工作流">
        {SCENARIO_WORKFLOW_STEPS.map((step) => (
          <button
            key={step.key}
            type="button"
            className={`bh-button ${workflowStep === step.key ? 'bh-button--yellow' : ''}`}
            onClick={() => setWorkflowStep(step.key)}
          >
            {step.label}
          </button>
        ))}
      </div>

      {workflowStep === 'import' && <div className="bh-panel" style={{ marginTop: 12, padding: 12 }}>
        <span className="bh-eyebrow">IMPORT</span>
        <strong>多模态剧本导入</strong>
        <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
          <input className="bh-input" placeholder="剧本标题（不填则自动生成）" value={importTitle} onChange={(e) => setImportTitle(e.target.value)} />
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 220px) minmax(180px, 1fr)', gap: 8 }}>
            <select className="bh-input" value={licenseType} onChange={(e) => setLicenseType(e.target.value)}>
              <option value="authorized">authorized</option>
              <option value="open">open</option>
            </select>
            <input className="bh-input" placeholder="授权凭证或引用（可选）" value={licenseRef} onChange={(e) => setLicenseRef(e.target.value)} />
          </div>
          <label className="bh-upload-box">
            <span>{importFiles.length > 0 ? `已选择 ${importFiles.length} 个文件` : '选择 PDF / DOCX / 图片源文件'}</span>
            <input
              type="file"
              accept={SCENARIO_IMPORT_ACCEPT}
              multiple
              disabled={importing}
              onChange={(e) => {
                const files = Array.from(e.target.files || []);
                setImportFiles(files);
                if (!importTitle.trim()) setImportTitle(getDefaultImportTitle(files));
                e.target.value = '';
              }}
            />
          </label>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="bh-button bh-button--yellow" onClick={handleImport} disabled={importing}>
              {importing ? '导入中...' : '开始导入'}
            </button>
            {importFiles.length > 0 && (
              <button className="bh-button" onClick={() => setImportFiles([])} disabled={importing}>清空文件</button>
            )}
          </div>
        </div>
        {importError && <div className="bh-muted-box" style={{ color: 'var(--bh-red)', marginTop: 8 }}>{importError}</div>}
        <ScenarioImportStatusCard
          importResult={importResult}
          retrying={retrying}
          retryError={retryError}
          onRetry={retryImportRecognition}
        />
      </div>}

      <div style={{ display: 'grid', gridTemplateColumns: workflowStep !== 'import' && selectedId ? '1fr 1fr' : '1fr', gap: 16, marginTop: 16 }}>
        <div className="bh-preset-list">
          {scenarios.length === 0 ? (
            <div className="bh-muted-box" style={{ padding: 24, textAlign: 'center' }}>
              还没有剧本，先从上方导入入口开始。
            </div>
          ) : (
            scenarios.map((scenario) => {
              const status = getScenarioStatusMeta(getScenarioDisplayStatus(scenario));
              return (
                <div
                  key={scenario.scenario_id}
                  className={`bh-preset-card ${selectedId === scenario.scenario_id ? 'bh-preset-card--selected' : ''}`}
                  style={{ position: 'relative' }}
                  onClick={() => selectScenario(scenario.scenario_id)}
                >
                  <strong>{scenario.title || scenario.scenario_id}</strong>
                  <span style={{ fontSize: 10, opacity: 0.8, color: status.color }}>
                    {status.label} ({getScenarioDisplayStatus(scenario)})
                  </span>
                  <label style={{ position: 'absolute', right: 10, top: 10, display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 11 }}>
                    <span>选择</span>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(scenario.scenario_id)}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => toggleScenarioSelected(scenario.scenario_id, event.target.checked)}
                    />
                  </label>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                    <button
                      className="bh-button bh-button--red"
                      style={{ padding: '2px 8px', fontSize: 11 }}
                      onClick={(event) => {
                        event.stopPropagation();
                        void deleteScenario(scenario.scenario_id);
                      }}
                      disabled={deleting}
                    >
                      删除
                    </button>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {selectedId && workflowStep !== 'import' && (
          <div className="bh-preview-box">
            <span className="bh-eyebrow">{selectedScenarioStatus.eyebrow}</span>
            <h3>{selectedScenario?.title || selectedId}</h3>
            <p>
              导入状态：
              <strong style={{ color: selectedScenarioStatus.color }}>
                {selectedScenarioStatus.label} ({getScenarioDisplayStatus(selectedScenario)})
              </strong>
            </p>

            <div className="bh-panel" style={{ padding: 12, marginTop: 12 }}>
              <span className="bh-eyebrow">VERSIONS</span>
              <strong>版本管理</strong>
              {loadingVersions ? (
                <div className="bh-muted-box" style={{ marginTop: 8 }}>版本加载中...</div>
              ) : versions.length === 0 ? (
                <div className="bh-muted-box" style={{ marginTop: 8 }}>当前剧本还没有可查看的版本。</div>
              ) : (
                <div className="bh-preset-list" style={{ marginTop: 8 }}>
                  {versions.map((version) => {
                    const status = getScenarioStatusMeta(version.status);
                    return (
                      <button
                        key={version.scenario_version_id}
                        className={`bh-preset-card ${selectedVersionId === version.scenario_version_id ? 'bh-preset-card--selected' : ''}`}
                        onClick={() => loadVersionDetail(selectedId, version.scenario_version_id, versions)}
                        style={{ textAlign: 'left' }}
                      >
                        <strong>版本 #{version.version_number || '?'}</strong>
                        <span style={{ color: status.color }}>{status.label} ({version.status || 'draft'})</span>
                        <small>{version.is_active ? '当前发布版本' : `创建于 ${formatDateText(version.created_at)}`}</small>
                      </button>
                    );
                  })}
                </div>
              )}
              {versionError && <div className="bh-muted-box" style={{ color: 'var(--bh-red)', marginTop: 8 }}>{versionError}</div>}
              {publishError && <div className="bh-muted-box" style={{ color: 'var(--bh-red)', marginTop: 8 }}>{publishError}</div>}
              {publishSuccess && <div className="bh-muted-box" style={{ color: 'var(--bh-blue)', marginTop: 8 }}>{publishSuccess}</div>}
            </div>

            {workflowStep === 'review' && <div style={{ marginTop: 12 }}>
              {selectedVersionId ? (
                <ScenarioReviewWorkbench
                  scenarioId={selectedId}
                  scenarioVersionId={selectedVersionId}
                  onVersionChanged={(nextVersionId) => { void loadVersions(selectedId, nextVersionId); }}
                />
              ) : <div className="bh-muted-box">请选择一个剧本版本开始审核。</div>}
            </div>}

            {workflowStep === 'publish' && <div style={{ marginTop: 12 }}>
              {loadingPrep ? (
                <div className="bh-muted-box">正在加载质量报告与 AI 备团包...</div>
              ) : (
                <ScenarioVersionInspector
                  scenarioTitle={selectedScenario?.title || selectedId}
                  versionDetail={versionDetail}
                  publishChecked={publishChecked}
                  publishNotes={publishNotes}
                  publishing={publishing}
                  onPublishCheckedChange={setPublishChecked}
                  onPublishNotesChange={setPublishNotes}
                  onPublish={publishVersion}
                />
              )}
            </div>}

            {workflowStep === 'assets' && <MapDraftReviewPanel
              scenarioId={selectedId}
              scenarioVersionId={selectedVersionId}
              assets={assets}
            />}
            {workflowStep === 'assets' && <ScenarioAssetBindingsPanel
              scenarioId={selectedId}
              scenarioVersionId={selectedVersionId}
            />}

            {workflowStep === 'assets' && <label className="bh-upload-box" style={{ marginTop: 12 }}>
              <span>{uploading ? '上传中...' : '上传素材文件'}</span>
              <input type="file" accept="image/*,audio/*,video/*,.pdf" multiple disabled={uploading}
                onChange={(e) => { if (e.target.files) { for (let i = 0; i < e.target.files.length; i++) uploadAsset(selectedId, e.target.files[i]); } e.target.value = ''; }} />
            </label>}

            {workflowStep === 'assets' && <div className="bh-preset-list" style={{ marginTop: 12 }}>
              {assets.length === 0 && <div className="bh-muted-box">暂无素材</div>}
              {assets.map((a: any) => (
                <div key={a.asset_id} className="bh-skill-row" style={{ padding: '8px' }}>
                  <span>{a.original_name}</span>
                  <span style={{ fontSize: 11, color: 'var(--bh-muted)' }}>{(a.file_size / 1024).toFixed(0)} KB</span>
                  <button className="bh-button bh-button--red" style={{ minHeight: 28, padding: '2px 8px', fontSize: 11 }}
                    onClick={() => deleteAsset(selectedId, a.asset_id)}>删除</button>
                </div>
              ))}
            </div>}
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
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [editing, setEditing] = useState<string | null>(null);
  const [form, setForm] = useState<Record<string, any>>({});
  const [deleteMessage, setDeleteMessage] = useState('');
  const [deleting, setDeleting] = useState(false);

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

  const toggleSelected = (id: string, checked: boolean) => {
    setSelectedIds((prev) => (checked ? [...prev.filter((value) => value !== id), id] : prev.filter((value) => value !== id)));
    setDeleteMessage('');
  };

  const deleteChar = async (id: string) => {
    if (!window.confirm('确定要删除该角色吗？')) return;
    setDeleting(true);
    setDeleteMessage('');
    try {
      await api(`/api/admin/characters/${id}`, { method: 'DELETE' });
      setSelectedIds((prev) => prev.filter((characterId) => characterId !== id));
      load();
      setDeleteMessage(`已删除角色 ${id}`);
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  const batchDelete = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`确定要删除 ${selectedIds.length} 个角色吗？`)) return;
    setDeleting(true);
    setDeleteMessage('');
    try {
      const result = await api('/api/admin/characters/batch-delete', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedIds }),
      }) as Record<string, any>;
      const deletedIds = Array.isArray(result.deleted_ids) ? result.deleted_ids : [];
      const errors = Array.isArray(result.errors) ? result.errors : [];
      setSelectedIds((prev) => prev.filter((id) => !deletedIds.includes(id)));
      load();
      if (errors.length > 0) {
        const failed = errors.map((item: any) => `${item.id}:${item.error}`).join('；');
        setDeleteMessage(`已删除 ${deletedIds.length} 个，失败 ${errors.length} 个：${failed}`);
      } else {
        setDeleteMessage(`已删除 ${deletedIds.length} 个角色`);
      }
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <section>
      <h2 className="bh-panel-title">角色管理</h2>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input className="bh-input" placeholder="按房间码过滤" value={roomFilter} onChange={(e) => setRoomFilter(e.target.value)} style={{ width: 200 }} />
        {selectedIds.length > 0 && (
          <button className="bh-button bh-button--red" onClick={batchDelete} disabled={deleting}>批量删除（{selectedIds.length}）</button>
        )}
        <button className="bh-button" onClick={load}>刷新</button>
      </div>
      {deleteMessage && <div className="bh-muted-box" style={{ marginBottom: 12 }}>{deleteMessage}</div>}

      <div className="bh-preset-list">
        {chars.map((c) => (
          <div key={c.character_id} className="bh-preset-card" style={{ textAlign: 'left', position: 'relative' }}>
            <label style={{ position: 'absolute', right: 10, top: 10, display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 11 }}>
              <span>选择</span>
              <input
                type="checkbox"
                checked={selectedIds.includes(c.character_id)}
                onClick={(event) => event.stopPropagation()}
                onChange={(event) => toggleSelected(c.character_id, event.target.checked)}
              />
            </label>
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
            <button
              className="bh-button bh-button--red"
              style={{ minHeight: 28, fontSize: 11, padding: '2px 10px', marginTop: 6, marginLeft: 6 }}
              onClick={() => void deleteChar(c.character_id)}
              disabled={deleting}
            >
              删除
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}

// ── Accounts ──

function AccountsPanel() {
  const [accounts, setAccounts] = useState<any[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [deleteMessage, setDeleteMessage] = useState('');
  const [deleting, setDeleting] = useState(false);
  const load = () => api('/api/admin/accounts').then(setAccounts);
  useEffect(() => { load(); }, []);

  const toggleSelected = (id: string, checked: boolean) => {
    setSelectedIds((prev) => (checked ? [...prev.filter((value) => value !== id), id] : prev.filter((value) => value !== id)));
    setDeleteMessage('');
  };

  const deleteAccount = async (id: string) => {
    if (!window.confirm('确定要删除该账号吗？')) return;
    setDeleting(true);
    setDeleteMessage('');
    try {
      await api(`/api/admin/accounts/${id}`, { method: 'DELETE' });
      setSelectedIds((prev) => prev.filter((accountId) => accountId !== id));
      load();
      setDeleteMessage(`已删除账号 ${id}`);
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  const batchDelete = async () => {
    if (selectedIds.length === 0) return;
    if (!window.confirm(`确定要删除 ${selectedIds.length} 个账号吗？`)) return;
    setDeleting(true);
    setDeleteMessage('');
    try {
      const result = await api('/api/admin/accounts/batch-delete', {
        method: 'POST',
        body: JSON.stringify({ ids: selectedIds }),
      }) as Record<string, any>;
      const deletedIds = Array.isArray(result.deleted_ids) ? result.deleted_ids : [];
      const errors = Array.isArray(result.errors) ? result.errors : [];
      setSelectedIds((prev) => prev.filter((id) => !deletedIds.includes(id)));
      load();
      if (errors.length > 0) {
        const failed = errors.map((item: any) => `${item.id}:${item.error}`).join('；');
        setDeleteMessage(`已删除 ${deletedIds.length} 个，失败 ${errors.length} 个：${failed}`);
      } else {
        setDeleteMessage(`已删除 ${deletedIds.length} 个账号`);
      }
    } catch (error) {
      setDeleteMessage(coerceErrorMessage(error));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 className="bh-panel-title">账号管理</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {selectedIds.length > 0 && (
            <button className="bh-button bh-button--red" onClick={batchDelete} disabled={deleting}>
              批量删除（{selectedIds.length}）
            </button>
          )}
        <button className="bh-button" onClick={load}>刷新</button>
        </div>
      </div>
      {deleteMessage && <div className="bh-muted-box" style={{ marginTop: 8, marginBottom: 8 }}>{deleteMessage}</div>}
      <div className="bh-preset-list" style={{ marginTop: 16 }}>
        {accounts.map((a) => (
          <div key={a.account_id} className="bh-preset-card" style={{ textAlign: 'left', position: 'relative' }}>
            <label style={{ position: 'absolute', right: 10, top: 10, display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 11 }}>
              <span>选择</span>
              <input
                type="checkbox"
                checked={selectedIds.includes(a.account_id)}
                onChange={(event) => toggleSelected(a.account_id, event.target.checked)}
                onClick={(event) => event.stopPropagation()}
              />
            </label>
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
              <button
                className="bh-button bh-button--red"
                style={{ fontSize: 11, padding: '4px 8px' }}
                onClick={() => void deleteAccount(a.account_id)}
                disabled={deleting}
              >
                删除
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
