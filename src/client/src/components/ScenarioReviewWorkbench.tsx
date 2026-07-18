import { useEffect, useMemo, useState } from 'react';
import { getSlotValue } from '../shared/identity';
import { summarizeReviewIssues } from '../shared/scenario-review-workbench';

type ReviewIssue = {
  issue_id: string;
  code: string;
  category: string;
  severity: string;
  message: string;
  blocking: boolean;
  target_type: string;
  target_key: string;
  resolution_hint: string;
  status: 'open' | 'not_applicable';
  resolution_rationale: string;
};

type SourcePart = {
  source_part_id: string;
  source_document_id: string;
  source_title: string;
  source_filename: string;
  source_mime_type: string;
  page_number?: number;
  text_content: string;
  anchor: Record<string, unknown>;
};

type PatchCandidate = {
  target_type: string;
  target_key: string;
  payload: Record<string, unknown>;
  provenance: 'source' | 'curator';
  citation: Record<string, unknown>;
  rationale: string;
  confidence?: number;
};

type ReviewWorkbench = {
  scenario_title: string;
  status: string;
  is_review_draft: boolean;
  issues: ReviewIssue[];
  source_parts: SourcePart[];
  knowledge_graph: Record<string, unknown>;
  prep_package: Record<string, unknown>;
};

type ViewMode = 'todo' | 'source' | 'timeline';

function authHeaders(): Record<string, string> {
  const token = getSlotValue('account_token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function requestJson(path: string, options?: RequestInit) {
  const headers = new Headers(options?.headers);
  headers.set('Content-Type', 'application/json');
  Object.entries(authHeaders()).forEach(([key, value]) => headers.set(key, value));
  const response = await fetch(path, {
    ...options,
    headers,
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(typeof body.detail === 'string' ? body.detail : '审核请求失败，请稍后重试。');
  }
  return body;
}

function sourceLabel(part: SourcePart) {
  const page = part.page_number ? `第 ${part.page_number} 页` : '解析片段';
  return `${part.source_filename || part.source_title || '原始文件'} · ${page}`;
}

function extractTimeline(graph: Record<string, unknown>) {
  const scenes = Array.isArray(graph.scenes) ? graph.scenes : [];
  const clues = Array.isArray(graph.clues) ? graph.clues : [];
  const endings = Array.isArray(graph.endings) ? graph.endings : [];
  return [
    ...scenes.map((item: any, index) => ({ kind: '场景', index, title: item.name || item.scene_id || '未命名场景', text: item.description || item.summary || '' })),
    ...clues.map((item: any, index) => ({ kind: '线索', index, title: item.name || item.clue_id || '未命名线索', text: item.description || item.text || '' })),
    ...endings.map((item: any, index) => ({ kind: '结局', index, title: item.name || item.ending_id || '未命名结局', text: item.summary || item.description || '' })),
  ];
}

export function ScenarioReviewWorkbench({
  scenarioId,
  scenarioVersionId,
  onVersionChanged,
}: {
  scenarioId: string;
  scenarioVersionId: string;
  onVersionChanged: (scenarioVersionId: string) => void;
}) {
  const [workbench, setWorkbench] = useState<ReviewWorkbench | null>(null);
  const [view, setView] = useState<ViewMode>('todo');
  const [selectedIssueId, setSelectedIssueId] = useState('');
  const [selectedPartId, setSelectedPartId] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [candidates, setCandidates] = useState<PatchCandidate[]>([]);
  const [aiSummary, setAiSummary] = useState('');
  const [originalUrl, setOriginalUrl] = useState('');
  const [targetType, setTargetType] = useState('clue');
  const [targetKey, setTargetKey] = useState('');
  const [payloadText, setPayloadText] = useState('{\n  "name": ""\n}');
  const [provenance, setProvenance] = useState<'source' | 'curator'>('source');
  const [rationale, setRationale] = useState('');

  const basePath = `/api/scenarios/${scenarioId}/versions/${scenarioVersionId}`;
  const selectedIssue = useMemo(
    () => workbench?.issues.find((issue) => issue.issue_id === selectedIssueId) || workbench?.issues[0],
    [workbench, selectedIssueId],
  );
  const selectedPart = useMemo(
    () => workbench?.source_parts.find((part) => part.source_part_id === selectedPartId) || workbench?.source_parts[0],
    [workbench, selectedPartId],
  );
  const summary = useMemo(() => summarizeReviewIssues(workbench?.issues || []), [workbench]);
  const timeline = useMemo(() => extractTimeline(workbench?.knowledge_graph || {}), [workbench]);

  const load = async () => {
    if (!scenarioId || !scenarioVersionId) return;
    setLoading(true);
    setError('');
    try {
      const next = await requestJson(`${basePath}/review-workbench`) as ReviewWorkbench;
      setWorkbench(next);
      setSelectedIssueId((current) => current || next.issues[0]?.issue_id || '');
      setSelectedPartId((current) => current || next.source_parts[0]?.source_part_id || '');
    } catch (loadError) {
      setWorkbench(null);
      setError(loadError instanceof Error ? loadError.message : '无法加载审核工作台。');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { void load(); }, [scenarioId, scenarioVersionId]);

  useEffect(() => {
    if (!selectedPart?.source_document_id) return undefined;
    let active = true;
    const controller = new AbortController();
    fetch(`${basePath}/review-sources/${selectedPart.source_document_id}`, {
      headers: authHeaders(),
      signal: controller.signal,
    })
      .then((response) => (response.ok ? response.blob() : Promise.reject(new Error('source unavailable'))))
      .then((blob) => {
        if (!active) return;
        setOriginalUrl((current) => {
          if (current) URL.revokeObjectURL(current);
          return URL.createObjectURL(blob);
        });
      })
      .catch(() => { if (active) setOriginalUrl(''); });
    return () => {
      active = false;
      controller.abort();
    };
  }, [basePath, selectedPart?.source_document_id]);

  useEffect(() => () => { if (originalUrl) URL.revokeObjectURL(originalUrl); }, [originalUrl]);

  useEffect(() => {
    if (!selectedIssue) return;
    setTargetType(selectedIssue.target_type || 'clue');
    setTargetKey(selectedIssue.target_key || '');
  }, [selectedIssue?.issue_id]);

  const createDraft = async () => {
    setBusy('draft');
    setError('');
    try {
      const created = await requestJson(`${basePath}/review-drafts`, { method: 'POST' });
      onVersionChanged(created.scenario_version_id);
    } catch (draftError) {
      setError(draftError instanceof Error ? draftError.message : '无法创建审核草稿。');
    } finally {
      setBusy('');
    }
  };

  const savePatch = async (candidate?: PatchCandidate) => {
    if (!workbench?.is_review_draft) return;
    let payload: Record<string, unknown>;
    try {
      payload = candidate?.payload || JSON.parse(payloadText);
    } catch {
      setError('补充内容必须是有效 JSON。');
      return;
    }
    const patch = candidate || {
      target_type: targetType,
      target_key: targetKey.trim(),
      payload,
      provenance,
      citation: provenance === 'source' && selectedPart ? {
        source_part_id: selectedPart.source_part_id,
        page_number: selectedPart.page_number,
      } : {},
      rationale: provenance === 'curator' ? rationale.trim() : '',
    };
    if (!patch.target_key) {
      setError('请填写稳定标识，例如 clue_id 或场景 ID。');
      return;
    }
    setBusy('patch');
    setError('');
    try {
      await requestJson(`${basePath}/review-patches`, { method: 'POST', body: JSON.stringify(patch) });
      setMessage('补充已加入审核草稿；点击“重编译并复查”后才会写入备团包。');
      setCandidates((items) => items.filter((item) => item !== candidate));
    } catch (patchError) {
      setError(patchError instanceof Error ? patchError.message : '无法保存补充。');
    } finally {
      setBusy('');
    }
  };

  const rebuild = async () => {
    setBusy('rebuild');
    setError('');
    try {
      await requestJson(`${basePath}/review-rebuild`, { method: 'POST' });
      setMessage('已根据已接受的补充重编译，并更新完整性检查。');
      await load();
    } catch (rebuildError) {
      setError(rebuildError instanceof Error ? rebuildError.message : '重编译失败。');
    } finally {
      setBusy('');
    }
  };

  const askAi = async (mode: 'issue' | 'whole') => {
    if (mode === 'issue' && !selectedIssue) return;
    setBusy(mode === 'issue' ? 'ai-issue' : 'ai-whole');
    setError('');
    try {
      const result = await requestJson(
        `${basePath}/review-ai/${mode === 'issue' ? 'issue' : 'reread'}`,
        {
          method: 'POST',
          body: mode === 'issue' ? JSON.stringify({ issue_id: selectedIssue?.issue_id }) : undefined,
        },
      );
      setAiSummary(String(result.summary || ''));
      setCandidates(Array.isArray(result.suggestions) ? result.suggestions : []);
      setMessage('AI 只生成了待确认候选；请逐条检查证据后采用。');
    } catch (aiError) {
      setError(aiError instanceof Error ? aiError.message : 'AI 复核暂时不可用。');
    } finally {
      setBusy('');
    }
  };

  const markNotApplicable = async (issue: ReviewIssue) => {
    const reason = window.prompt('说明为什么该非核心项不适用于此模组：', issue.resolution_rationale || '');
    if (!reason?.trim()) return;
    setBusy(`waive-${issue.issue_id}`);
    setError('');
    try {
      await requestJson(`${basePath}/review-issues/resolve`, {
        method: 'POST',
        body: JSON.stringify({ issue_id: issue.issue_id, resolution: 'not_applicable', rationale: reason.trim() }),
      });
      await load();
    } catch (resolveError) {
      setError(resolveError instanceof Error ? resolveError.message : '无法记录不适用理由。');
    } finally {
      setBusy('');
    }
  };

  if (loading && !workbench) return <div className="bh-muted-box">正在载入 AI 备团审核台…</div>;
  if (error && !workbench) return <div className="bh-muted-box" style={{ color: 'var(--bh-red)' }}>{error}</div>;
  if (!workbench) return null;

  return (
    <div style={{ display: 'grid', gap: 12 }} data-testid="scenario-review-workbench">
      <div className="bh-panel" style={{ padding: 12 }}>
        <span className="bh-eyebrow">REVIEW WORKBENCH</span>
        <strong>{workbench.scenario_title || '剧本审核'} · 版本化 AI 备团</strong>
        <p style={{ marginTop: 6 }}>原件与 AI 结构化结果并排检查；所有补充先进入新审核草稿，发布版本不会被直接改写。</p>
        <div className="bh-grid-links" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', marginTop: 8 }}>
          <div className="bh-link-card"><span className="bh-eyebrow">CORE</span><strong>{summary.blocking}</strong><span>必须修复</span></div>
          <div className="bh-link-card"><span className="bh-eyebrow">TODO</span><strong>{summary.open}</strong><span>待处理</span></div>
          <div className="bh-link-card"><span className="bh-eyebrow">N/A</span><strong>{summary.notApplicable}</strong><span>已留理由</span></div>
        </div>
        {!workbench.is_review_draft && (
          <button className="bh-button bh-button--yellow" style={{ marginTop: 10 }} onClick={createDraft} disabled={busy === 'draft'}>
            {busy === 'draft' ? '正在创建…' : '从此版本创建审核草稿'}
          </button>
        )}
      </div>

      <div className="bh-source-toggle" aria-label="审核视图">
        {([['todo', '完整性待办'], ['source', '原文 + AI 备团'], ['timeline', '剧情时间线']] as const).map(([key, label]) => (
          <button key={key} type="button" className={`bh-button ${view === key ? 'bh-button--yellow' : ''}`} onClick={() => setView(key)}>{label}</button>
        ))}
      </div>

      {error && <div className="bh-muted-box" style={{ color: 'var(--bh-red)' }}>{error}</div>}
      {message && <div className="bh-muted-box" style={{ color: 'var(--bh-blue)' }}>{message}</div>}

      {view === 'todo' && (
        <div className="bh-preset-list">
          {workbench.issues.length === 0 && <div className="bh-muted-box">完整性检查已无待办项。</div>}
          {workbench.issues.map((issue) => (
            <div key={issue.issue_id} className="bh-panel" style={{ padding: 12, borderColor: issue.blocking ? 'var(--bh-red)' : undefined }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                <strong>{issue.blocking ? '核心缺失' : '可选完善'} · {issue.message}</strong>
                <span>{issue.status === 'not_applicable' ? '不适用（已留理由）' : issue.severity}</span>
              </div>
              <p style={{ marginTop: 6 }}>{issue.resolution_hint || '核对原文后补充结构化内容。'}</p>
              {issue.status === 'not_applicable' && <small>理由：{issue.resolution_rationale}</small>}
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
                <button className="bh-button" onClick={() => { setSelectedIssueId(issue.issue_id); setView('source'); }}>查看原文并补充</button>
                {workbench.is_review_draft && <button className="bh-button" disabled={busy === 'ai-issue'} onClick={() => { setSelectedIssueId(issue.issue_id); void askAi('issue'); }}>AI 找证据并起草</button>}
                {!issue.blocking && issue.status !== 'not_applicable' && workbench.is_review_draft && <button className="bh-button" disabled={busy === `waive-${issue.issue_id}`} onClick={() => void markNotApplicable(issue)}>标记不适用</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {view === 'source' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'minmax(260px, 1fr) minmax(320px, 1fr)', gap: 12 }}>
          <div className="bh-panel" style={{ padding: 12, minWidth: 0 }}>
            <span className="bh-eyebrow">SOURCE FIRST</span>
            <select className="bh-input" value={selectedPart?.source_part_id || ''} onChange={(event) => setSelectedPartId(event.target.value)} style={{ marginTop: 8 }}>
              {workbench.source_parts.map((part) => <option key={part.source_part_id} value={part.source_part_id}>{sourceLabel(part)}</option>)}
            </select>
            {selectedPart && <>
              <div className="bh-muted-box" style={{ marginTop: 8 }}>
                <strong>{sourceLabel(selectedPart)}</strong>
                {originalUrl ? <a href={originalUrl} target="_blank" rel="noreferrer" style={{ marginLeft: 8 }}>打开原件</a> : <span style={{ marginLeft: 8 }}>原件不可用，显示解析文本</span>}
              </div>
              {originalUrl && selectedPart.source_mime_type.startsWith('image/') && <img src={originalUrl} alt={selectedPart.source_filename} style={{ width: '100%', maxHeight: 420, objectFit: 'contain', marginTop: 8, border: '3px solid var(--bh-black)' }} />}
              {originalUrl && selectedPart.source_mime_type === 'application/pdf' && <iframe title="原始 PDF" src={originalUrl} style={{ width: '100%', height: 360, marginTop: 8, border: '3px solid var(--bh-black)' }} />}
              <pre className="bh-muted-box" style={{ marginTop: 8, whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto' }}>{selectedPart.text_content || '该页没有可提取文本；请打开原件查看。'}</pre>
            </>}
          </div>
          <div className="bh-panel" style={{ padding: 12, minWidth: 0 }}>
            <span className="bh-eyebrow">AI PREP / SUPPLEMENT</span>
            {selectedIssue && <div className="bh-muted-box" style={{ marginTop: 8 }}><strong>{selectedIssue.message}</strong><br />{selectedIssue.resolution_hint}</div>}
            {!workbench.is_review_draft ? <div className="bh-muted-box" style={{ marginTop: 8 }}>先创建审核草稿，才能保存补充内容。</div> : <>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
                <input className="bh-input" value={targetType} onChange={(event) => setTargetType(event.target.value)} placeholder="类型：clue / scene / npc" />
                <input className="bh-input" value={targetKey} onChange={(event) => setTargetKey(event.target.value)} placeholder="稳定 ID" />
              </div>
              <textarea className="bh-input" value={payloadText} onChange={(event) => setPayloadText(event.target.value)} style={{ minHeight: 150, marginTop: 8, fontFamily: 'monospace' }} aria-label="结构化补充 JSON" />
              <label style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}><input type="radio" checked={provenance === 'source'} onChange={() => setProvenance('source')} />原文依据（自动引用当前页）</label>
              <label style={{ display: 'flex', gap: 8, marginTop: 4, alignItems: 'center' }}><input type="radio" checked={provenance === 'curator'} onChange={() => setProvenance('curator')} />管理员补写（必须说明理由）</label>
              {provenance === 'curator' && <textarea className="bh-input" value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="补写理由和来源限制" style={{ minHeight: 72, marginTop: 8 }} />}
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
                <button className="bh-button bh-button--yellow" disabled={busy === 'patch'} onClick={() => void savePatch()}>加入审核草稿</button>
                <button className="bh-button" disabled={busy === 'ai-issue'} onClick={() => void askAi('issue')}>AI 找证据并起草</button>
                <button className="bh-button" disabled={busy === 'ai-whole'} onClick={() => void askAi('whole')}>AI 整本重读</button>
                <button className="bh-button" disabled={busy === 'rebuild'} onClick={() => void rebuild()}>重编译并复查</button>
              </div>
            </>}
            {(aiSummary || candidates.length > 0) && <div className="bh-muted-box" style={{ marginTop: 12 }}><strong>AI 候选（未写入）</strong><p>{aiSummary}</p>{candidates.map((candidate, index) => <div key={`${candidate.target_key}-${index}`} style={{ borderTop: '1px solid var(--bh-black)', paddingTop: 8, marginTop: 8 }}><strong>{candidate.target_type}: {candidate.target_key}</strong><small style={{ display: 'block' }}>置信度 {Math.round((candidate.confidence || 0) * 100)}% · 引用 {String(candidate.citation.source_part_id || '无')}</small><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(candidate.payload, null, 2)}</pre><button className="bh-button" disabled={busy === 'patch'} onClick={() => void savePatch(candidate)}>采用此草稿</button></div>)}</div>}
          </div>
        </div>
      )}

      {view === 'timeline' && <div className="bh-preset-list">{timeline.length === 0 ? <div className="bh-muted-box">AI 备团包尚无可展示的场景、线索或结局。</div> : timeline.map((entry) => <div key={`${entry.kind}-${entry.index}`} className="bh-panel" style={{ padding: 12 }}><span className="bh-eyebrow">{entry.kind}</span><strong>{entry.title}</strong>{entry.text && <p style={{ marginTop: 6 }}>{entry.text}</p>}</div>)}</div>}
    </div>
  );
}
