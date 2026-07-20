import { useEffect, useMemo, useState } from 'react';
import {
  createEvidence,
  createEvidenceNote,
  createEvidenceComment,
  createEvidenceLink,
  createPersonalObjective,
  closePartyQuestion,
  confirmSessionZero,
  createPlayerNote,
  getSessionZero,
  getCampaignHome,
  getEvidenceDetail,
  listEvidence,
  listPlayerNotes,
  markPartyQuestionExplained,
  previewPartyQuestionClose,
  reopenPartyQuestion,
  revertSharedHypothesisStatus,
  shareEvidence,
  suggestSharedHypothesisDisproof,
  updateSharedHypothesisStatus,
  sharePlayerNote,
  uploadPlayerNoteAttachment,
} from '../shared/player-api';
import type { CampaignHomeDTO, EvidenceCardDTO, EvidenceDetailDTO, PlayerNoteDTO } from '../shared/types';
import type {
  EvidenceCommentDTO,
  HypothesisDisproofSuggestion,
  PartyQuestionClosePreview,
  SessionZeroDTO,
} from '../shared/player-api';
import { getSlotValue } from '../shared/identity';
import RedactedCitationDisclosure from './RedactedCitationDisclosure';


interface EvidenceState {
  cards: EvidenceCardDTO[];
  links: Array<{
    evidence_link_id: string;
    from_evidence_card_id: string;
    to_evidence_card_id: string;
    relation_type: string;
  }>;
  comments: EvidenceCommentDTO[];
}

const emptyEvidence: EvidenceState = { cards: [], links: [], comments: [] };

type CurrentScene = NonNullable<CampaignHomeDTO['current_scene']>;

export function EvidenceShareEditor({
  card,
  title,
  body,
  onTitleChange,
  onBodyChange,
  onSubmit,
  onCancel,
}: {
  card: EvidenceCardDTO;
  title: string;
  body: string;
  onTitleChange: (value: string) => void;
  onBodyChange: (value: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  return (
    <section className="bh-muted-box" aria-label={`分享证据副本：${card.title}`}>
      <strong>分享为队伍副本</strong>
      <p>原私人卡不会被修改；请编辑队伍可见的标题和摘要。</p>
      <input className="bh-input" value={title} onChange={(event) => onTitleChange(event.target.value)} placeholder="队伍可见标题" />
      <textarea className="bh-input" value={body} onChange={(event) => onBodyChange(event.target.value)} placeholder="队伍可见摘要" rows={2} />
      <div className="bh-action-row">
        <button className="bh-button bh-button--yellow" type="button" disabled={!title.trim()} onClick={onSubmit}>保存队伍副本</button>
        <button className="bh-button" type="button" onClick={onCancel}>取消</button>
      </div>
    </section>
  );
}

export function SharedHypothesisCollaboration({
  comments,
  draft,
  onDraftChange,
  onSubmit,
}: {
  comments: EvidenceCommentDTO[];
  draft: string;
  onDraftChange: (value: string) => void;
  onSubmit: () => void;
}) {
  return (
    <section className="bh-muted-box" aria-label="共享假说协作">
      <strong>共享假说协作</strong>
      <p>可关联：支持资料、矛盾资料、相关资料；不以人数决定结论。</p>
      {comments.length > 0 && (
        <ul>
          {comments.map((comment, index) => <li key={`${comment.author_name}:${index}`}><strong>{comment.author_name}</strong>：{comment.body}</li>)}
        </ul>
      )}
      <textarea className="bh-input" value={draft} onChange={(event) => onDraftChange(event.target.value)} placeholder="补充支持、矛盾或相关资料的说明" rows={2} />
      <button className="bh-button" type="button" disabled={!draft.trim()} onClick={onSubmit}>添加评论</button>
    </section>
  );
}

export function SharedHypothesisStatusControls({
  status,
  undoAvailable,
  onStatusChange,
  onApply,
  onRevert,
}: {
  status: 'discussing' | 'disproved' | 'shelved';
  undoAvailable: boolean;
  onStatusChange: (status: 'discussing' | 'disproved' | 'shelved') => void;
  onApply: () => void;
  onRevert: () => void;
}) {
  return (
    <section className="bh-muted-box" aria-label="共享假说状态">
      <strong>假说状态</strong>
      <p>AI 只能提出建议；由玩家确认后才会更新公共记录。</p>
      <div className="bh-action-row">
        <select className="bh-input" value={status} onChange={(event) => onStatusChange(event.target.value as typeof status)}>
          <option value="discussing">讨论中</option>
          <option value="disproved">已证伪</option>
          <option value="shelved">已搁置</option>
        </select>
        <button className="bh-button" type="button" onClick={onApply}>更新状态</button>
        {undoAvailable && <button className="bh-button" type="button" onClick={onRevert}>撤销状态更改</button>}
      </div>
    </section>
  );
}

export function RelatedEvidenceSelector({
  cards,
  selectedCardIds,
  onToggle,
}: {
  cards: EvidenceCardDTO[];
  selectedCardIds: string[];
  onToggle: (evidenceCardId: string) => void;
}) {
  const partyCards = cards.filter((card) => card.visibility === 'party').slice(0, 5);
  if (!partyCards.length) return null;
  return (
    <fieldset className="bh-muted-box" aria-label="可选关联资料">
      <legend>可选关联资料</legend>
      <p>仅显示近期队伍资料；不会提示“正确证据”。</p>
      {partyCards.map((card) => (
        <label key={card.evidence_card_id} className="bh-choice-row">
          <input
            type="checkbox"
            checked={selectedCardIds.includes(card.evidence_card_id)}
            onChange={() => onToggle(card.evidence_card_id)}
          />
          {card.title}
        </label>
      ))}
    </fieldset>
  );
}

export function HypothesisDisproofSuggestionCard({
  suggestion,
  factTitles,
  unavailableReason,
  onCheck,
  onFillDisproved,
}: {
  suggestion: HypothesisDisproofSuggestion | null | undefined;
  factTitles: string[];
  unavailableReason?: string;
  onCheck: () => void;
  onFillDisproved: () => void;
}) {
  return (
    <section className="bh-muted-box" aria-label="AI 假说建议">
      <strong>AI 证据检查</strong>
      <p>AI 只能提出建议，不能更改状态。</p>
      <button className="bh-button" type="button" onClick={onCheck}>检查已确认事实</button>
      {suggestion && (
        <div>
          <p><strong>可能已证伪</strong>：{suggestion.reason}</p>
          {factTitles.length > 0 && <p>依据：{factTitles.join('、')}</p>}
          <p>仅建议，未更改状态。</p>
          <button className="bh-button" type="button" onClick={onFillDisproved}>填入“已证伪”</button>
        </div>
      )}
      {!suggestion && unavailableReason && <p>{unavailableReason}</p>}
    </section>
  );
}

function PlayerAssetImage({ assetId, alt }: { assetId: string; alt: string }) {
  const endpoint = `/api/player/assets/${encodeURIComponent(assetId)}`;
  const [src, setSrc] = useState('');

  useEffect(() => {
    let active = true;
    fetch(endpoint, {
      headers: { 'X-Room-Token': getSlotValue('player_token') || '' },
    })
      .then((response) => response.ok ? response.blob() : null)
      .then((blob) => {
        if (!blob || !active) return;
        setSrc(URL.createObjectURL(blob));
      })
      .catch(() => setSrc(''));
    return () => {
      active = false;
      setSrc((current) => {
        if (current) URL.revokeObjectURL(current);
        return '';
      });
    };
  }, [endpoint]);

  return (
    <div aria-label={alt} data-asset-endpoint={endpoint}>
      {src && (
        <img
          alt={alt}
          src={src}
          style={{ width: '100%', maxHeight: 360, objectFit: 'contain', border: '3px solid var(--bh-black)' }}
        />
      )}
    </div>
  );
}

export function CampaignCurrentSceneCard({
  scene,
  onContinue,
}: {
  scene: CurrentScene;
  onContinue: () => void;
}) {
  return (
    <div className="bh-campaign-home__section">
      <span className="bh-eyebrow">CURRENT SCENE</span>
      <h3>当前场景</h3>
      {scene.image_asset_id && (
        <PlayerAssetImage assetId={scene.image_asset_id} alt="当前场景插图" />
      )}
      <p>{scene.text_preview}</p>
      <p className="bh-muted">{scene.choice_count} 个可选方向</p>
      {scene.citation?.verified && (
        <RedactedCitationDisclosure citations={[scene.citation]} />
      )}
      <button className="bh-button bh-button--yellow" type="button" onClick={onContinue}>
        继续当前场景
      </button>
    </div>
  );
}

export function CampaignRecentClues({
  clues,
}: {
  clues: CampaignHomeDTO['recent_clues'];
}) {
  return (
    <div className="bh-campaign-home__section">
      <h3>最近线索</h3>
      {clues.length ? (
        <div className="bh-campaign-home__list">
          {clues.map((clue) => (
            <div className="bh-muted-box" key={clue.clue_id}>
              <strong>{clue.is_owner ? '我的发现' : '队伍分享摘要'}</strong>
              <p>{clue.text}</p>
              <small>{new Date(clue.discovered_at).toLocaleString()}</small>
            </div>
          ))}
        </div>
      ) : (
        <p>暂无已发现的线索。</p>
      )}
    </div>
  );
}

export function CampaignUnresolvedQuestions({
  questions,
}: {
  questions: CampaignHomeDTO['unresolved_questions'];
}) {
  return (
    <div className="bh-campaign-home__questions">
      <strong>未解决问题</strong>
      {questions.length ? (
        <ul>{questions.slice(0, 3).map((question) => <li key={question.evidence_card_id}>{question.title}</li>)}</ul>
      ) : <p>暂无公开的待调查问题。</p>}
    </div>
  );
}

export function PartyQuestionCard({
  card,
  undoAvailable,
  onMarkExplained,
  onPreviewClose,
  onReopen,
}: {
  card: EvidenceCardDTO;
  undoAvailable: boolean;
  onMarkExplained: () => void;
  onPreviewClose: () => void;
  onReopen: () => void;
}) {
  const questionStatus = card.question_status || 'investigating';
  return (
    <article className="bh-muted-box">
      <strong>{card.title}</strong> <span>· {card.fact_status === 'hypothesis' ? '猜测' : card.fact_status === 'confirmed' ? '已确认' : '已排除'}</span>
      <span> · {questionStatusLabel(questionStatus)}</span>
      <p>{card.body}</p>
      <div className="bh-action-row">
        {questionStatus === 'closed' ? (
          <button className="bh-button" type="button" onClick={onReopen}>
            {undoAvailable ? '撤销关闭' : '重新打开'}
          </button>
        ) : (
          <>
            <button className="bh-button" type="button" onClick={onMarkExplained}>标记已有解释</button>
            <button className="bh-button" type="button" onClick={onPreviewClose}>关闭问题</button>
          </>
        )}
      </div>
    </article>
  );
}

export function InvestigationDetailCard({
  detail,
  onAddNote,
  onShare,
}: {
  detail: EvidenceDetailDTO;
  onAddNote: () => void;
  onShare: () => void;
}) {
  const renderKnownItems = (items: EvidenceDetailDTO['current_known']) => (
    <ul>
      {items.map((item) => (
        <li key={item.evidence_card_id}>
          <strong>{item.title}</strong> <span>· {item.cognitive_tag}</span>
          <p>{item.body}</p>
        </li>
      ))}
    </ul>
  );
  return (
    <article className="bh-muted-box" aria-label={`资料详情：${detail.summary.title}`}>
      <strong>资料详情：{detail.summary.title}</strong>
      <details open>
        <summary>摘要</summary>
        <p>{detail.summary.body || '暂无可公开的摘要。'}</p>
      </details>
      <details>
        <summary>当前已知 · {detail.current_known.length} 条</summary>
        {detail.current_known.length ? renderKnownItems(detail.current_known) : <p>暂无当前已知资料。</p>}
      </details>
      <details>
        <summary>相关资料 · {detail.related_materials.length} 项</summary>
        {detail.related_materials.length ? renderKnownItems(detail.related_materials) : <p>暂无玩家可见的相关资料。</p>}
      </details>
      <details>
        <summary>玩家笔记 · {detail.player_notes.length} 条</summary>
        {detail.player_notes.length ? (
          <ul>{detail.player_notes.map((note) => <li key={note.note_id}><strong>{note.title}</strong><p>{note.body}</p></li>)}</ul>
        ) : <p>还没有关联的私人笔记。</p>}
      </details>
      <div className="bh-action-row">
        <button className="bh-button" type="button" onClick={onAddNote}>加入笔记</button>
        {detail.summary.visibility === 'private' && (
          <button className="bh-button" type="button" onClick={onShare}>分享给队伍</button>
        )}
        <details>
          <summary>更多</summary>
          <p>资料只会显示你当前有权看到的内容。</p>
        </details>
      </div>
    </article>
  );
}

export default function CampaignHomePanel({
  roomId,
  onContinueScene = () => {},
}: {
  roomId: string;
  onContinueScene?: () => void;
}) {
  const [home, setHome] = useState<CampaignHomeDTO | null>(null);
  const [notes, setNotes] = useState<PlayerNoteDTO[]>([]);
  const [evidence, setEvidence] = useState<EvidenceState>(emptyEvidence);
  const [sessionZero, setSessionZero] = useState<SessionZeroDTO | null>(null);
  const [error, setError] = useState('');
  const [noteTitle, setNoteTitle] = useState('');
  const [noteBody, setNoteBody] = useState('');
  const [evidenceTitle, setEvidenceTitle] = useState('');
  const [evidenceBody, setEvidenceBody] = useState('');
  const [evidenceType, setEvidenceType] = useState<EvidenceCardDTO['card_type']>('clue');
  const [relatedEvidenceCardIds, setRelatedEvidenceCardIds] = useState<string[]>([]);
  const [linkFrom, setLinkFrom] = useState('');
  const [linkTo, setLinkTo] = useState('');
  const [linkRelation, setLinkRelation] = useState<'support' | 'contradict' | 'related'>('related');
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const [hypothesisStatusDrafts, setHypothesisStatusDrafts] = useState<Record<string, 'discussing' | 'disproved' | 'shelved'>>({});
  const [hypothesisUndoCardId, setHypothesisUndoCardId] = useState('');
  const [disproofSuggestions, setDisproofSuggestions] = useState<Record<string, HypothesisDisproofSuggestion | null>>({});
  const [disproofSuggestionReasons, setDisproofSuggestionReasons] = useState<Record<string, string>>({});
  const [personalObjective, setPersonalObjective] = useState('');
  const [questionClosePreview, setQuestionClosePreview] = useState<PartyQuestionClosePreview | null>(null);
  const [questionUndoCardId, setQuestionUndoCardId] = useState('');
  const [shareCard, setShareCard] = useState<EvidenceCardDTO | null>(null);
  const [shareTitle, setShareTitle] = useState('');
  const [shareBody, setShareBody] = useState('');
  const [evidenceDetail, setEvidenceDetail] = useState<EvidenceDetailDTO | null>(null);
  const [evidenceNoteTitle, setEvidenceNoteTitle] = useState('');
  const [evidenceNoteBody, setEvidenceNoteBody] = useState('');
  const [evidenceNoteComposerOpen, setEvidenceNoteComposerOpen] = useState(false);

  const refresh = async () => {
    try {
      setError('');
      const [nextHome, nextNotes, nextEvidence, nextSessionZero] = await Promise.all([
        getCampaignHome(),
        listPlayerNotes(),
        listEvidence(roomId),
        getSessionZero(),
      ]);
      setHome(nextHome);
      setNotes(nextNotes.notes);
      setEvidence(nextEvidence);
      setSessionZero(nextSessionZero);
    } catch {
      setError('战役信息暂时无法同步；不会影响服务器上的已确认行动。');
    }
  };

  useEffect(() => { void refresh(); }, [roomId]);

  const cardTitles = useMemo(
    () => new Map(evidence.cards.map((card) => [card.evidence_card_id, card.title])),
    [evidence.cards],
  );

  const createNote = async () => {
    if (!noteTitle.trim() || !noteBody.trim()) return;
    try {
      await createPlayerNote(noteTitle.trim(), noteBody.trim());
      setNoteTitle('');
      setNoteBody('');
      await refresh();
    } catch {
      setError('私人笔记未能保存。');
    }
  };

  const addPersonalObjective = async () => {
    if (!personalObjective.trim()) return;
    try {
      await createPersonalObjective(personalObjective.trim());
      setPersonalObjective('');
      await refresh();
    } catch {
      setError('个人目标未能保存。');
    }
  };

  const confirmSessionZeroStep = async (step: string) => {
    try {
      await confirmSessionZero(step);
      await refresh();
    } catch {
      setError('请按顺序完成 Session Zero 确认。');
    }
  };

  const shareNote = async (note: PlayerNoteDTO) => {
    const summary = window.prompt('输入给队伍看的脱敏摘要：');
    if (!summary?.trim()) return;
    try {
      await sharePlayerNote(note.note_id, note.title, summary.trim());
      await refresh();
    } catch {
      setError('脱敏副本未能分享。');
    }
  };

  const addAttachment = async (noteId: string, file: File | undefined) => {
    if (!file) return;
    try {
      await uploadPlayerNoteAttachment(noteId, file);
      await refresh();
    } catch {
      setError('图片附件未能保存；每条笔记只允许一张图片。');
    }
  };

  const addEvidence = async () => {
    if (!evidenceTitle.trim()) return;
    try {
      await createEvidence(roomId, {
        title: evidenceTitle.trim(),
        body: evidenceBody.trim(),
        card_type: evidenceType,
        visibility: evidenceType === 'question' ? 'party' : 'private',
        related_evidence_card_ids: relatedEvidenceCardIds,
      });
      setEvidenceTitle('');
      setEvidenceBody('');
      setRelatedEvidenceCardIds([]);
      await refresh();
    } catch {
      setError('证据卡未能创建。');
    }
  };

  const openEvidenceShare = (card: EvidenceCardDTO) => {
    setShareCard(card);
    setShareTitle(card.title);
    setShareBody(card.body);
  };

  const openEvidenceDetail = async (card: EvidenceCardDTO) => {
    try {
      setError('');
      setEvidenceDetail(await getEvidenceDetail(roomId, card.evidence_card_id));
      setEvidenceNoteComposerOpen(false);
    } catch {
      setError('资料详情暂时无法读取；不会显示任何不可见资料。');
    }
  };

  const createLinkedEvidenceNote = async () => {
    if (!evidenceDetail || !evidenceNoteTitle.trim() || !evidenceNoteBody.trim()) return;
    try {
      await createEvidenceNote(
        roomId,
        evidenceDetail.summary.evidence_card_id,
        evidenceNoteTitle.trim(),
        evidenceNoteBody.trim(),
      );
      setEvidenceNoteTitle('');
      setEvidenceNoteBody('');
      setEvidenceNoteComposerOpen(false);
      setEvidenceDetail(await getEvidenceDetail(roomId, evidenceDetail.summary.evidence_card_id));
      await refresh();
    } catch {
      setError('关联私人笔记未能保存。');
    }
  };

  const cancelEvidenceShare = () => {
    setShareCard(null);
    setShareTitle('');
    setShareBody('');
  };

  const submitEvidenceShare = async () => {
    if (!shareCard || !shareTitle.trim()) return;
    try {
      await shareEvidence(roomId, shareCard.evidence_card_id, shareTitle.trim(), shareBody.trim());
      cancelEvidenceShare();
      await refresh();
    } catch {
      setError('队伍副本未能保存；请确认原卡仍只属于你。');
    }
  };

  const addEvidenceLink = async () => {
    if (!linkFrom || !linkTo || linkFrom === linkTo) return;
    try {
      await createEvidenceLink(roomId, linkFrom, linkTo, linkRelation);
      await refresh();
    } catch {
      setError('关系线未能创建。');
    }
  };

  const addEvidenceComment = async (card: EvidenceCardDTO) => {
    const body = (commentDrafts[card.evidence_card_id] || '').trim();
    if (!body) return;
    try {
      await createEvidenceComment(roomId, card.evidence_card_id, body);
      setCommentDrafts((previous) => ({ ...previous, [card.evidence_card_id]: '' }));
      await refresh();
    } catch {
      setError('评论未能保存；请确认这是队伍共享的玩家假说。');
    }
  };

  const updateHypothesisStatus = async (card: EvidenceCardDTO) => {
    const status = hypothesisStatusDrafts[card.evidence_card_id]
      || card.hypothesis_status
      || 'discussing';
    try {
      const result = await updateSharedHypothesisStatus(roomId, card.evidence_card_id, status);
      setHypothesisUndoCardId(result.undo_available ? card.evidence_card_id : '');
      if (result.undo_available) {
        window.setTimeout(() => {
          setHypothesisUndoCardId((current) => current === card.evidence_card_id ? '' : current);
        }, 10_000);
      }
      await refresh();
    } catch {
      setError('假说状态未能更新；请确认这是队伍共享的玩家假说。');
    }
  };

  const revertHypothesisStatus = async (card: EvidenceCardDTO) => {
    try {
      await revertSharedHypothesisStatus(roomId, card.evidence_card_id);
      setHypothesisUndoCardId('');
      await refresh();
    } catch {
      setError('撤销窗口已结束，或该状态由其他玩家更新。');
    }
  };

  const inspectHypothesisForDisproof = async (card: EvidenceCardDTO) => {
    try {
      const response = await suggestSharedHypothesisDisproof(roomId, card.evidence_card_id);
      setDisproofSuggestions((current) => ({ ...current, [card.evidence_card_id]: response.suggestion }));
      const reasonLabels: Record<string, string> = {
        no_confirmed_linked_facts: '请先关联至少一条已确认的队伍资料。',
        ai_unavailable: 'AI 建议暂不可用；你仍可自行更新状态。',
        no_supported_disproof: 'AI 没有找到足以支持“可能已证伪”的关联事实。',
      };
      setDisproofSuggestionReasons((current) => ({
        ...current,
        [card.evidence_card_id]: response.reason ? reasonLabels[response.reason] : '',
      }));
    } catch {
      setError('AI 证据检查暂不可用；假说状态不会被自动改变。');
    }
  };

  const previewQuestionClose = async (card: EvidenceCardDTO) => {
    try {
      setError('');
      setQuestionClosePreview(await previewPartyQuestionClose(roomId, card.evidence_card_id));
    } catch {
      setError('关闭问题前无法读取关联资料。');
    }
  };

  const closeQuestion = async () => {
    if (!questionClosePreview) return;
    const relatedTitles = questionClosePreview.related_hypotheses.map((item) => item.title).join('、');
    const confirmed = window.confirm(
      `关闭不会删除资料。${relatedTitles ? `仍关联：${relatedTitles}。` : '当前没有关联假说。'}确认关闭这个问题吗？`,
    );
    if (!confirmed) return;
    try {
      const result = await closePartyQuestion(roomId, questionClosePreview.question.evidence_card_id);
      setQuestionClosePreview(null);
      setQuestionUndoCardId(result.undo_available ? result.card.evidence_card_id : '');
      if (result.undo_available) {
        window.setTimeout(() => {
          setQuestionUndoCardId((current) => current === result.card.evidence_card_id ? '' : current);
        }, 10_000);
      }
      await refresh();
    } catch {
      setError('问题未能关闭；请重新检查关联资料后再试。');
    }
  };

  const reopenQuestion = async (card: EvidenceCardDTO) => {
    try {
      const result = await reopenPartyQuestion(roomId, card.evidence_card_id);
      setQuestionUndoCardId('');
      setError(result.undid_close ? '已撤销关闭，问题恢复待调查。' : '问题已重新打开，关联资料仍被保留。');
      await refresh();
    } catch {
      setError('问题未能重新打开。');
    }
  };

  const markQuestionExplained = async (card: EvidenceCardDTO) => {
    try {
      await markPartyQuestionExplained(roomId, card.evidence_card_id);
      setError('问题已标记为“已有解释”，仍可继续调查或关闭。');
      await refresh();
    } catch {
      setError('请先关联至少一条队伍假说，再标记为已有解释。');
    }
  };

  return (
    <section className="bh-panel bh-campaign-home">
      <span className="bh-eyebrow">CAMPAIGN RETURN</span>
      <h2 className="bh-panel-title">战役回流</h2>
      {error && <div className="bh-error" role="alert">{error}</div>}

      {home?.current_scene && (
        <CampaignCurrentSceneCard scene={home.current_scene} onContinue={onContinueScene} />
      )}

      <CampaignRecentClues clues={home?.recent_clues || []} />

      <div className="bh-campaign-home__section">
        <h3>本场状态</h3>
        <p>{home?.session?.status === 'active' ? 'Session 进行中' : '从上次权威状态继续'}</p>
        <p>{home?.last_summary?.summary_text || '暂无已发布的 Session 摘要。'}</p>
        <strong>引用依据</strong>
        <ul>
          {home?.last_summary?.citations?.length
            ? home.last_summary.citations.map((citation) => (
              <li key={`${citation.event_sequence}:${citation.citation_label}`}>
                事件 #{citation.event_sequence} · {citation.citation_label}
              </li>
            ))
            : <li>当前摘要暂无可公开的事件引用。</li>}
        </ul>
        {home?.next_session?.scheduled_for && (
          <p>下一场：{new Date(home.next_session.scheduled_for).toLocaleString()}（{home.next_session.attendance_status || '尚未回复'}）</p>
        )}
        <div className="bh-campaign-home__columns">
          <div>
            <strong>队伍目标</strong>
            <ul>{home?.team_objectives.map((item) => <li key={item.objective_id}>{item.text}</li>)}</ul>
          </div>
          <div>
            <strong>个人目标</strong>
            <ul>{home?.personal_objectives.map((item) => <li key={item.objective_id}>{item.text}</li>)}</ul>
            <input className="bh-input" value={personalObjective} onChange={(event) => setPersonalObjective(event.target.value)} placeholder="我的下一步目标" />
            <button className="bh-button" type="button" onClick={() => void addPersonalObjective()}>新增个人目标</button>
          </div>
        </div>
        <CampaignUnresolvedQuestions questions={home?.unresolved_questions || []} />
      </div>

      <div className="bh-campaign-home__section">
        <h3>Session Zero</h3>
        <p>按顺序确认角色与规则、安全边界、AI/Host 裁决、私人数据和连接设备。</p>
        <div className="bh-campaign-home__list">
          {(sessionZero?.steps || [
            { step: 'character_rules', confirmed: false }, { step: 'safety', confirmed: false },
            { step: 'ai_host', confirmed: false }, { step: 'private_data', confirmed: false },
            { step: 'connection', confirmed: false },
          ]).map((item) => (
            <div key={item.step} className="bh-muted-box">
              <span>{sessionZeroLabel(item.step)}</span>
              <button className="bh-button" type="button" disabled={item.confirmed} onClick={() => void confirmSessionZeroStep(item.step)}>
                {item.confirmed ? '已确认' : '确认'}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="bh-campaign-home__section">
        <h3>私人笔记</h3>
        <p>仅你可见；分享会创建单独的脱敏副本。</p>
        <input className="bh-input" value={noteTitle} onChange={(event) => setNoteTitle(event.target.value)} placeholder="笔记标题" />
        <textarea className="bh-input" value={noteBody} onChange={(event) => setNoteBody(event.target.value)} placeholder="记录你的推测、线索或计划" rows={3} />
        <button className="bh-button bh-button--blue" type="button" onClick={() => void createNote()}>保存私人笔记</button>
        <div className="bh-campaign-home__list">
          {notes.map((note) => (
            <article key={note.note_id} className="bh-muted-box">
              <strong>{note.title}</strong>
              <p>{note.body}</p>
              <span>{note.visibility === 'party' ? '队伍脱敏副本' : '仅自己可见'}</span>
              {note.visibility === 'private' && (
                <button className="bh-button" type="button" onClick={() => void shareNote(note)}>分享脱敏副本</button>
              )}
              <label className="bh-button">添加图片<input hidden type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(event) => void addAttachment(note.note_id, event.target.files?.[0])} /></label>
            </article>
          ))}
        </div>
      </div>

      <div className="bh-campaign-home__section">
        <h3>队伍证据板</h3>
        <p>玩家新增内容默认是猜测；只有系统或 Host 可以确认事实或排除。</p>
        {evidenceDetail && (
          <>
            <InvestigationDetailCard
              detail={evidenceDetail}
              onAddNote={() => setEvidenceNoteComposerOpen(true)}
              onShare={() => openEvidenceShare(evidenceDetail.summary)}
            />
            {evidenceNoteComposerOpen && (
              <section className="bh-muted-box" aria-label="关联私人笔记">
                <strong>加入私人笔记</strong>
                <p>只你可见；不会进入 AI 上下文。</p>
                <input className="bh-input" value={evidenceNoteTitle} onChange={(event) => setEvidenceNoteTitle(event.target.value)} placeholder="笔记标题" />
                <textarea className="bh-input" value={evidenceNoteBody} onChange={(event) => setEvidenceNoteBody(event.target.value)} placeholder="记录你的判断或计划" rows={3} />
                <div className="bh-action-row">
                  <button className="bh-button bh-button--blue" type="button" disabled={!evidenceNoteTitle.trim() || !evidenceNoteBody.trim()} onClick={() => void createLinkedEvidenceNote()}>保存关联笔记</button>
                  <button className="bh-button" type="button" onClick={() => setEvidenceNoteComposerOpen(false)}>取消</button>
                </div>
              </section>
            )}
          </>
        )}
        <input className="bh-input" value={evidenceTitle} onChange={(event) => setEvidenceTitle(event.target.value)} placeholder="证据标题或问题" />
        <textarea className="bh-input" value={evidenceBody} onChange={(event) => setEvidenceBody(event.target.value)} placeholder="说明为何值得记录" rows={2} />
        <select className="bh-input" value={evidenceType} onChange={(event) => setEvidenceType(event.target.value as EvidenceCardDTO['card_type'])}>
          <option value="clue">线索</option><option value="person">人物</option><option value="location">地点</option><option value="item">物品</option><option value="question">未解决问题</option>
        </select>
        <RelatedEvidenceSelector
          cards={evidence.cards}
          selectedCardIds={relatedEvidenceCardIds}
          onToggle={(evidenceCardId) => setRelatedEvidenceCardIds((current) => (
            current.includes(evidenceCardId)
              ? current.filter((cardId) => cardId !== evidenceCardId)
              : [...current, evidenceCardId]
          ))}
        />
        <button className="bh-button bh-button--yellow" type="button" onClick={() => void addEvidence()}>新增猜测卡</button>
        {questionClosePreview && (
          <section className="bh-muted-box" aria-label="关闭问题确认">
            <strong>关闭问题前确认：{questionClosePreview.question.title}</strong>
            <p>关闭不会删除问题、关联假说或争议资料；之后仍可重新打开。</p>
            {questionClosePreview.related_hypotheses.length > 0 ? (
              <ul>
                {questionClosePreview.related_hypotheses.map((item) => <li key={item.evidence_card_id}>关联假说：{item.title}</li>)}
              </ul>
            ) : <p>当前没有关联假说。</p>}
            <div className="bh-action-row">
              <button className="bh-button bh-button--yellow" type="button" onClick={() => void closeQuestion()}>确认关闭</button>
              <button className="bh-button" type="button" onClick={() => setQuestionClosePreview(null)}>取消</button>
            </div>
          </section>
        )}
        <div className="bh-campaign-home__list">
          {evidence.cards.map((card) => {
            const isPartyQuestion = card.card_type === 'question' && card.visibility === 'party';
            const isSharedHypothesis = card.visibility === 'party'
              && card.card_type !== 'question'
              && card.source === 'player'
              && card.fact_status === 'hypothesis';
            return isPartyQuestion ? (
              <PartyQuestionCard
                key={card.evidence_card_id}
                card={card}
                undoAvailable={questionUndoCardId === card.evidence_card_id}
                onMarkExplained={() => void markQuestionExplained(card)}
                onPreviewClose={() => void previewQuestionClose(card)}
                onReopen={() => void reopenQuestion(card)}
              />
            ) : (
              <article key={card.evidence_card_id} className="bh-muted-box">
                <strong>{card.title}</strong> <span>· {card.fact_status === 'hypothesis' ? '猜测' : card.fact_status === 'confirmed' ? '已确认' : '已排除'}</span>
                <p>{card.body}</p>
                <button className="bh-button" type="button" onClick={() => void openEvidenceDetail(card)}>查看详情</button>
                {card.visibility === 'private' && (shareCard?.evidence_card_id === card.evidence_card_id ? (
                  <EvidenceShareEditor
                    card={card}
                    title={shareTitle}
                    body={shareBody}
                    onTitleChange={setShareTitle}
                    onBodyChange={setShareBody}
                    onSubmit={() => void submitEvidenceShare()}
                    onCancel={cancelEvidenceShare}
                  />
                ) : (
                  <button className="bh-button" type="button" onClick={() => openEvidenceShare(card)}>分享为队伍副本</button>
                ))}
                {isSharedHypothesis && (
                  <>
                    <SharedHypothesisCollaboration
                      comments={evidence.comments.filter((comment) => comment.evidence_card_id === card.evidence_card_id)}
                      draft={commentDrafts[card.evidence_card_id] || ''}
                      onDraftChange={(value) => setCommentDrafts((previous) => ({ ...previous, [card.evidence_card_id]: value }))}
                      onSubmit={() => void addEvidenceComment(card)}
                    />
                    <SharedHypothesisStatusControls
                      status={hypothesisStatusDrafts[card.evidence_card_id] || card.hypothesis_status || 'discussing'}
                      undoAvailable={hypothesisUndoCardId === card.evidence_card_id}
                      onStatusChange={(status) => setHypothesisStatusDrafts((previous) => ({ ...previous, [card.evidence_card_id]: status }))}
                      onApply={() => void updateHypothesisStatus(card)}
                      onRevert={() => void revertHypothesisStatus(card)}
                    />
                    <HypothesisDisproofSuggestionCard
                      suggestion={disproofSuggestions[card.evidence_card_id]}
                      factTitles={(disproofSuggestions[card.evidence_card_id]?.factIds || []).map(
                        (factId) => cardTitles.get(factId) || '已确认的队伍资料',
                      )}
                      unavailableReason={disproofSuggestionReasons[card.evidence_card_id]}
                      onCheck={() => void inspectHypothesisForDisproof(card)}
                      onFillDisproved={() => setHypothesisStatusDrafts((current) => ({
                        ...current,
                        [card.evidence_card_id]: 'disproved',
                      }))}
                    />
                  </>
                )}
              </article>
            );
          })}
        </div>
        {evidence.cards.length > 1 && (
          <div className="bh-campaign-home__link-form">
            <select className="bh-input" value={linkFrom} onChange={(event) => setLinkFrom(event.target.value)}><option value="">关系起点</option>{evidence.cards.map((card) => <option key={card.evidence_card_id} value={card.evidence_card_id}>{card.title}</option>)}</select>
            <select className="bh-input" value={linkTo} onChange={(event) => setLinkTo(event.target.value)}><option value="">关系终点</option>{evidence.cards.map((card) => <option key={card.evidence_card_id} value={card.evidence_card_id}>{card.title}</option>)}</select>
            <select className="bh-input" value={linkRelation} onChange={(event) => setLinkRelation(event.target.value as 'support' | 'contradict' | 'related')}><option value="support">支持资料</option><option value="contradict">矛盾资料</option><option value="related">相关资料</option></select>
            <button className="bh-button" type="button" onClick={() => void addEvidenceLink()}>连接关系</button>
            {evidence.links.map((link) => <p key={link.evidence_link_id}>{cardTitles.get(link.from_evidence_card_id)} — {link.relation_type === 'support' ? '支持' : link.relation_type === 'contradict' ? '矛盾' : '相关'} → {cardTitles.get(link.to_evidence_card_id)}</p>)}
          </div>
        )}
      </div>
    </section>
  );
}


function sessionZeroLabel(step: string): string {
  const labels: Record<string, string> = {
    character_rules: '角色与规则',
    safety: '安全边界',
    ai_host: 'AI / Host 裁决方式',
    private_data: '私人数据与导出说明',
    connection: '连接与设备状态',
  };
  return labels[step] || step;
}

function questionStatusLabel(status: NonNullable<EvidenceCardDTO['question_status']>): string {
  const labels: Record<NonNullable<EvidenceCardDTO['question_status']>, string> = {
    investigating: '待调查',
    explained: '已有解释',
    closed: '已关闭',
  };
  return labels[status];
}
