import { useEffect, useMemo, useState } from 'react';
import {
  createEvidence,
  createEvidenceLink,
  createPersonalObjective,
  confirmSessionZero,
  createPlayerNote,
  getSessionZero,
  getCampaignHome,
  listEvidence,
  listPlayerNotes,
  sharePlayerNote,
  uploadPlayerNoteAttachment,
} from '../shared/player-api';
import type { CampaignHomeDTO, EvidenceCardDTO, PlayerNoteDTO } from '../shared/types';
import type { SessionZeroDTO } from '../shared/player-api';
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
}

const emptyEvidence: EvidenceState = { cards: [], links: [] };

type CurrentScene = NonNullable<CampaignHomeDTO['current_scene']>;

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
      <p className="bh-eyebrow" style={{ fontSize: 9 }}>
        {scene.choice_count} 个可选方向
      </p>
      {scene.citation?.verified && (
        <RedactedCitationDisclosure citations={[scene.citation]} />
      )}
      <button className="bh-button bh-button--yellow" type="button" onClick={onContinue}>
        继续当前场景
      </button>
    </div>
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
  const [linkFrom, setLinkFrom] = useState('');
  const [linkTo, setLinkTo] = useState('');
  const [personalObjective, setPersonalObjective] = useState('');

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
      });
      setEvidenceTitle('');
      setEvidenceBody('');
      await refresh();
    } catch {
      setError('证据卡未能创建。');
    }
  };

  const addEvidenceLink = async () => {
    if (!linkFrom || !linkTo || linkFrom === linkTo) return;
    try {
      await createEvidenceLink(roomId, linkFrom, linkTo, 'related');
      await refresh();
    } catch {
      setError('关系线未能创建。');
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
        <strong>未解决问题</strong>
        <ul>{home?.unresolved_questions.map((question) => <li key={question.evidence_card_id}>{question.title}</li>)}</ul>
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
        <input className="bh-input" value={evidenceTitle} onChange={(event) => setEvidenceTitle(event.target.value)} placeholder="证据标题或问题" />
        <textarea className="bh-input" value={evidenceBody} onChange={(event) => setEvidenceBody(event.target.value)} placeholder="说明为何值得记录" rows={2} />
        <select className="bh-input" value={evidenceType} onChange={(event) => setEvidenceType(event.target.value as EvidenceCardDTO['card_type'])}>
          <option value="clue">线索</option><option value="person">人物</option><option value="location">地点</option><option value="item">物品</option><option value="question">未解决问题</option>
        </select>
        <button className="bh-button bh-button--yellow" type="button" onClick={() => void addEvidence()}>新增猜测卡</button>
        <div className="bh-campaign-home__list">
          {evidence.cards.map((card) => (
            <article key={card.evidence_card_id} className="bh-muted-box">
              <strong>{card.title}</strong> <span>· {card.fact_status === 'hypothesis' ? '猜测' : card.fact_status === 'confirmed' ? '已确认' : '已排除'}</span>
              <p>{card.body}</p>
            </article>
          ))}
        </div>
        {evidence.cards.length > 1 && (
          <div className="bh-campaign-home__link-form">
            <select className="bh-input" value={linkFrom} onChange={(event) => setLinkFrom(event.target.value)}><option value="">关系起点</option>{evidence.cards.map((card) => <option key={card.evidence_card_id} value={card.evidence_card_id}>{card.title}</option>)}</select>
            <select className="bh-input" value={linkTo} onChange={(event) => setLinkTo(event.target.value)}><option value="">关系终点</option>{evidence.cards.map((card) => <option key={card.evidence_card_id} value={card.evidence_card_id}>{card.title}</option>)}</select>
            <button className="bh-button" type="button" onClick={() => void addEvidenceLink()}>连接关系</button>
            {evidence.links.map((link) => <p key={link.evidence_link_id}>{cardTitles.get(link.from_evidence_card_id)} → {cardTitles.get(link.to_evidence_card_id)}</p>)}
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
