import { useEffect, useMemo, useState } from 'react';
import { getSlotValue } from '../shared/identity';
import { resolveAiDraftIssueId, summarizeReviewIssues } from '../shared/scenario-review-workbench';
import {
  type ImageSuggestion,
  imageTargetLabel,
  normalizeImageSuggestion,
  partyVisibleImageNotice,
} from '../shared/scenario-review-images';

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

function isSpoilerBoundaryIssue(issue: ReviewIssue) {
  return issue.target_type === 'spoiler_boundary'
    || issue.code === 'missing_spoiler_boundaries'
    || issue.code === 'spoiler_boundary_coverage_incomplete';
}

function imageSuggestionTargetTypes(issue: ReviewIssue): Array<'scene' | 'npc' | 'item' | 'clue'> | null {
  if (issue.code === 'scene_images_missing') return ['scene'];
  if (issue.code === 'supporting_images_missing') return ['npc', 'item', 'clue'];
  return null;
}

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

function CandidatePayloadPreview({ candidate }: { candidate: PatchCandidate }) {
  if (candidate.target_type !== 'spoiler_boundary') {
    return <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(candidate.payload, null, 2)}</pre>;
  }
  const unlockClues = Array.isArray(candidate.payload.unlock_clues)
    ? candidate.payload.unlock_clues.map(String).filter(Boolean)
    : [];
  return (
    <dl style={{ display: 'grid', gap: 4, margin: '8px 0' }}>
      <div><dt>玩家看到什么</dt><dd>{String(candidate.payload.player_description || '未提供公开描述')}</dd></div>
      <div><dt>何时解锁</dt><dd>{String(candidate.payload.player_visibility || 'hidden')} {unlockClues.length ? `· 线索：${unlockClues.join('、')}` : ''}</dd></div>
      <div><dt>Host 所需信息</dt><dd>{String(candidate.payload.host_visibility || 'complete')}</dd></div>
      <div><dt>目标</dt><dd>{String(candidate.payload.target_type || '')}: {String(candidate.payload.target_id || '')}</dd></div>
    </dl>
  );
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
  const [imageSuggestions, setImageSuggestions] = useState<ImageSuggestion[]>([]);
  const [imageSummary, setImageSummary] = useState('');
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

  const askAi = async (mode: 'issue' | 'whole', clickedIssueId?: string) => {
    const issueId = resolveAiDraftIssueId(clickedIssueId, selectedIssue?.issue_id);
    if (mode === 'issue' && !issueId) return;
    setBusy(mode === 'issue' ? 'ai-issue' : 'ai-whole');
    setError('');
    try {
      const result = await requestJson(
        `${basePath}/review-ai/${mode === 'issue' ? 'issue' : 'reread'}`,
        {
          method: 'POST',
          body: mode === 'issue' ? JSON.stringify({ issue_id: issueId }) : undefined,
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

  const askImageSuggestions = async (targetTypes: Array<'scene' | 'npc' | 'item' | 'clue'>) => {
    if (!workbench?.is_review_draft) return;
    setBusy('image-suggestions');
    setError('');
    try {
      const result = await requestJson(
        `/api/admin/scenarios/${scenarioId}/versions/${scenarioVersionId}/image-generations/suggestions`,
        { method: 'POST', body: JSON.stringify({ target_types: targetTypes }) },
      );
      const suggestions = Array.isArray(result.suggestions)
        ? result.suggestions.filter((item: unknown): item is Record<string, unknown> => !!item && typeof item === 'object').map(normalizeImageSuggestion)
        : [];
      setImageSummary(String(result.summary || ''));
      setImageSuggestions(suggestions);
      setMessage('AI 已从原文起草待补配图；请编辑后生成预览，满意后再采用并绑定。');
    } catch (imageError) {
      setError(imageError instanceof Error ? imageError.message : 'AI 配图建议暂时不可用。');
    } finally {
      setBusy('');
    }
  };

  const imageSuggestionKey = (suggestion: ImageSuggestion) => `${suggestion.target_type}:${suggestion.target_key}`;

  const updateImageSuggestion = (suggestion: ImageSuggestion, patch: Partial<ImageSuggestion>) => {
    const key = imageSuggestionKey(suggestion);
    setImageSuggestions((items) => items.map((item) => imageSuggestionKey(item) === key ? { ...item, ...patch } : item));
  };

  const previewSceneImage = async (suggestion: ImageSuggestion) => {
    setBusy(`image-preview:${imageSuggestionKey(suggestion)}`);
    setError('');
    try {
      const result = await requestJson(
        `/api/admin/scenarios/${scenarioId}/versions/${scenarioVersionId}/image-generations/preview`,
        {
          method: 'POST',
          body: JSON.stringify({
            suggestion: {
              target_type: suggestion.target_type,
              target_key: suggestion.target_key,
              citation: suggestion.citation,
            },
            prompt: `${suggestion.prompt}\n风格：${suggestion.style}`,
            visibility: suggestion.visibility,
            size: '1024x1024',
          }),
        },
      );
      if (!result.data_url || !result.preview_token) throw new Error('图片服务没有返回可采用的预览。');
      updateImageSuggestion(suggestion, {
        preview: {
          data_url: String(result.data_url),
          preview_token: String(result.preview_token),
          generated_prompt: String(result.generated_prompt || ''),
          mime_type: String(result.mime_type || 'image/png'),
        },
      });
      setMessage('预览只在当前审核步骤中保留；确认采用后才会写入素材库和审核草稿。');
    } catch (previewError) {
      setError(previewError instanceof Error ? previewError.message : '生成图片预览失败。可继续使用手动上传素材。');
    } finally {
      setBusy('');
    }
  };

  const adoptSceneImage = async (suggestion: ImageSuggestion) => {
    if (!suggestion.preview) return;
    setBusy(`image-adopt:${imageSuggestionKey(suggestion)}`);
    setError('');
    try {
      await requestJson(
        `/api/admin/scenarios/${scenarioId}/versions/${scenarioVersionId}/image-generations/adopt`,
        {
          method: 'POST',
          body: JSON.stringify({
            preview_token: suggestion.preview.preview_token,
            data_url: suggestion.preview.data_url,
          }),
        },
      );
      setImageSuggestions((items) => items.filter((item) => imageSuggestionKey(item) !== imageSuggestionKey(suggestion)));
      setMessage('配图已绑定到审核草稿；点击“重编译并复查”后才会进入备团包。');
    } catch (adoptError) {
      setError(adoptError instanceof Error ? adoptError.message : '采用配图失败。');
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
                {workbench.is_review_draft && isSpoilerBoundaryIssue(issue) && <button className="bh-button" disabled={busy === 'ai-issue'} onClick={() => { setSelectedIssueId(issue.issue_id); setView('source'); void askAi('issue', issue.issue_id); }}>AI 起草可见性边界</button>}
                {workbench.is_review_draft && imageSuggestionTargetTypes(issue) && <button className="bh-button" disabled={busy === 'image-suggestions'} onClick={() => { setSelectedIssueId(issue.issue_id); setView('source'); void askImageSuggestions(imageSuggestionTargetTypes(issue) || ['scene']); }}>AI 从原文起草配图</button>}
                {workbench.is_review_draft && !isSpoilerBoundaryIssue(issue) && !imageSuggestionTargetTypes(issue) && <button className="bh-button" disabled={busy === 'ai-issue'} onClick={() => { setSelectedIssueId(issue.issue_id); void askAi('issue', issue.issue_id); }}>AI 找证据并起草</button>}
                {!issue.blocking && issue.status !== 'not_applicable' && workbench.is_review_draft && <button className="bh-button" disabled={busy === `waive-${issue.issue_id}`} onClick={() => void markNotApplicable(issue)}>标记不适用</button>}
              </div>
            </div>
          ))}
        </div>
      )}

      {view === 'source' && (
        <div className="scenario-review-source-grid">
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
              {originalUrl && selectedPart.source_mime_type.startsWith('image/') && <img src={originalUrl} alt={selectedPart.source_filename} style={{ width: '100%', maxHeight: 600, objectFit: 'contain', marginTop: 8, border: '3px solid var(--bh-black)' }} />}
              {originalUrl && selectedPart.source_mime_type === 'application/pdf' && <iframe title="原始 PDF" src={originalUrl} style={{ width: '100%', height: 560, marginTop: 8, border: '3px solid var(--bh-black)' }} />}
              <details open style={{ marginTop: 8 }}><summary>AI 读取到的纯文本节选（核对格式与 OCR）</summary><pre className="bh-muted-box" style={{ marginTop: 8, whiteSpace: 'pre-wrap', maxHeight: 440, overflow: 'auto' }}>{selectedPart.text_content || '该页没有可提取文本；请打开原件查看。'}</pre></details>
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
                <button className="bh-button" disabled={busy === 'image-suggestions'} onClick={() => void askImageSuggestions(['scene', 'npc', 'item', 'clue'])}>AI 起草所有待补配图</button>
                <button className="bh-button" disabled={busy === 'rebuild'} onClick={() => void rebuild()}>重编译并复查</button>
              </div>
            </>}
            {(aiSummary || candidates.length > 0) && <div className="bh-muted-box" style={{ marginTop: 12 }}><strong>AI 候选（未写入）</strong><p>{aiSummary}</p>{candidates.map((candidate, index) => <div key={`${candidate.target_key}-${index}`} style={{ borderTop: '1px solid var(--bh-black)', paddingTop: 8, marginTop: 8 }}><strong>{candidate.target_type}: {candidate.target_key}</strong><small style={{ display: 'block' }}>置信度 {Math.round((candidate.confidence || 0) * 100)}% · 引用 {String(candidate.citation.source_part_id || '无')}</small><CandidatePayloadPreview candidate={candidate} /><button className="bh-button" disabled={busy === 'patch'} onClick={() => void savePatch(candidate)}>采用此草稿</button></div>)}</div>}
            {(imageSummary || imageSuggestions.length > 0) && <div className="bh-muted-box" style={{ marginTop: 12 }}><strong>AI 配图建议（未写入）</strong><p>{imageSummary}</p>{imageSuggestions.map((suggestion) => <div key={imageSuggestionKey(suggestion)} style={{ borderTop: '1px solid var(--bh-black)', paddingTop: 10, marginTop: 10 }}><strong>{imageTargetLabel(suggestion.target_type)}：{suggestion.target_key}</strong><small style={{ display: 'block' }}>置信度 {Math.round(suggestion.confidence * 100)}% · 原文引用 {String(suggestion.citation.source_part_id || '无')}</small><p style={{ marginTop: 6 }}>{suggestion.image_summary}</p><label style={{ display: 'grid', gap: 4, marginTop: 8 }}>图片提示词<textarea className="bh-input" aria-label={`图片提示词 ${suggestion.target_key}`} value={suggestion.prompt} onChange={(event) => updateImageSuggestion(suggestion, { prompt: event.target.value })} style={{ minHeight: 90 }} /></label><label style={{ display: 'grid', gap: 4, marginTop: 8 }}>画面风格<input className="bh-input" value={suggestion.style} onChange={(event) => updateImageSuggestion(suggestion, { style: event.target.value })} /></label><label style={{ display: 'grid', gap: 4, marginTop: 8 }}>图片可见性<select className="bh-input" value={suggestion.visibility} onChange={(event) => updateImageSuggestion(suggestion, { visibility: event.target.value === 'party' ? 'party' : 'host_only', preview: undefined })}><option value="host_only">仅 Host</option><option value="party">队伍可见</option></select></label>{partyVisibleImageNotice(suggestion.visibility) && <small style={{ display: 'block', color: 'var(--bh-red)', marginTop: 6 }}>{partyVisibleImageNotice(suggestion.visibility)}</small>}{suggestion.preview && <><img src={suggestion.preview.data_url} alt={`${suggestion.target_key} 配图预览`} style={{ width: '100%', maxHeight: 420, objectFit: 'contain', border: '3px solid var(--bh-black)', marginTop: 10 }} /><small style={{ display: 'block', marginTop: 4 }}>实际生成提示词：{suggestion.preview.generated_prompt}</small></>}<div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 10 }}><button className="bh-button" disabled={busy === `image-preview:${imageSuggestionKey(suggestion)}`} onClick={() => void previewSceneImage(suggestion)}>{busy === `image-preview:${imageSuggestionKey(suggestion)}` ? '正在生成预览…' : '生成预览'}</button>{suggestion.preview && <button className="bh-button bh-button--yellow" disabled={busy === `image-adopt:${imageSuggestionKey(suggestion)}`} onClick={() => void adoptSceneImage(suggestion)}>{busy === `image-adopt:${imageSuggestionKey(suggestion)}` ? '正在采用…' : '采用并绑定'}</button>}</div></div>)}</div>}
          </div>
        </div>
      )}

      {view === 'timeline' && <div className="bh-preset-list">{timeline.length === 0 ? <div className="bh-muted-box">AI 备团包尚无可展示的场景、线索或结局。</div> : timeline.map((entry) => <div key={`${entry.kind}-${entry.index}`} className="bh-panel" style={{ padding: 12 }}><span className="bh-eyebrow">{entry.kind}</span><strong>{entry.title}</strong>{entry.text && <p style={{ marginTop: 6 }}>{entry.text}</p>}</div>)}</div>}
    </div>
  );
}
