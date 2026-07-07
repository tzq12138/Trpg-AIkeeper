import { useState } from 'react';
import { getSlotValue } from '../shared/identity';

interface Participant {
  characterId: string;
  side: 'player' | 'enemy' | 'neutral';
  hp: number; hpMax: number;
  san: number; sanMax: number;
  dex: number; mov: number;
  distanceBand: string;
  statusTags: string[];
  actedThisRound: boolean;
  weaponName: string;
  damageExpression: string;
  mainSkill: string;
  notes: string;
  displayName?: string;
  display_name?: string;
}

interface Encounter {
  encounterId: string;
  roomId: string;
  type: 'combat' | 'chase';
  status: 'suggested' | 'active' | 'resolved' | 'cancelled';
  currentRound: number;
  summary: string;
  participants: Participant[];
}

interface EncounterSuggestion {
  type: 'combat' | 'chase';
  reason: string;
  suggestedParticipants: Array<{
    name: string; side: string; hp: number; dex: number; mov: number;
    mainSkill?: string; damageExpression?: string;
  }>;
  initialDistance: string;
}

interface Props {
  roomId: string;
  activeEncounter: Encounter | null;
  encounterSuggestion: EncounterSuggestion | null;
  onEncounterConfirmed: () => void;
}

export default function EncounterPanel({
  roomId,
  activeEncounter,
  encounterSuggestion,
  onEncounterConfirmed,
}: Props) {
  const [npcName, setNpcName] = useState('');
  const [npcHp, setNpcHp] = useState('10');
  const [npcDex, setNpcDex] = useState('50');
  const [npcMov, setNpcMov] = useState('7');
  const [npcWeapon, setNpcWeapon] = useState('');
  const [npcDamage, setNpcDamage] = useState('1d3');
  const [npcSkill, setNpcSkill] = useState('');
  const [npcCreating, setNpcCreating] = useState(false);

  const token = getSlotValue('owner_token') || '';

  // ── Suggestion Card ──
  if (encounterSuggestion && !activeEncounter) {
    const handleConfirm = async () => {
      const res = await fetch(`/api/host/${encodeURIComponent(roomId)}/encounter/confirm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
        body: JSON.stringify({
          participants: encounterSuggestion.suggestedParticipants.map((p) => ({
            character_id: `npc:${crypto.randomUUID().slice(0, 6)}`,
            side: p.side || 'enemy',
            hp: p.hp || 10,
            hp_max: p.hp || 10,
            dex: p.dex || 50,
            mov: p.mov || 7,
            distance_band: encounterSuggestion.initialDistance || 'medium',
            weapon_name: p.damageExpression ? '武器' : '',
            damage_expression: p.damageExpression || '1d3',
            main_skill: p.mainSkill || '',
          })),
        }),
      });
      if (res.ok) onEncounterConfirmed();
    };

    const handleReject = async () => {
      onEncounterConfirmed();
    };

    return (
      <section className="bh-panel bh-encounter-suggestion">
        <span className="bh-eyebrow">ENCOUNTER SUGGESTION</span>
        <h2 className="bh-panel-title">
          {encounterSuggestion.type === 'combat' ? '⚔️ 战斗建议' : '🏃 追逐建议'}
        </h2>
        <p style={{ fontWeight: 700, marginTop: 8 }}>{encounterSuggestion.reason}</p>
        {encounterSuggestion.suggestedParticipants.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <strong>建议参与者：</strong>
            {encounterSuggestion.suggestedParticipants.map((p, i) => (
              <div key={i} className="bh-skeleton-row">
                <span>{p.name} ({p.side === 'enemy' ? '敌方' : '我方'})</span>
                <span>HP {p.hp} DEX {p.dex} MOV {p.mov}</span>
              </div>
            ))}
          </div>
        )}
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button className="bh-button bh-button--yellow" onClick={handleConfirm}>
            确认开始
          </button>
          <button className="bh-button bh-button--red" onClick={handleReject}>
            拒绝
          </button>
        </div>
      </section>
    );
  }

  // ── Active Encounter View ──
  if (activeEncounter) {
    const playerParts = activeEncounter.participants.filter((p) => p.side === 'player');
    const enemyParts = activeEncounter.participants.filter((p) => p.side === 'enemy');
    const neutralParts = activeEncounter.participants.filter((p) => p.side === 'neutral');

    const handleNextRound = async () => {
      await fetch(`/api/host/${encodeURIComponent(roomId)}/encounter/next-round`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
      });
      onEncounterConfirmed();
    };

    const handleResolve = async () => {
      await fetch(`/api/host/${encodeURIComponent(roomId)}/encounter/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
      });
      onEncounterConfirmed();
    };

    const handleCreateNpc = async () => {
      setNpcCreating(true);
      try {
        await fetch(`/api/host/${encodeURIComponent(roomId)}/encounter/npc`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-Owner-Token': token },
          body: JSON.stringify({
            encounter_id: activeEncounter.encounterId,
            name: npcName || '未命名NPC',
            side: 'enemy',
            hp: parseInt(npcHp) || 10,
            dex: parseInt(npcDex) || 50,
            mov: parseInt(npcMov) || 7,
            weapon_name: npcWeapon,
            damage_expression: npcDamage || '1d3',
            main_skill: npcSkill,
          }),
        });
        setNpcName(''); setNpcHp('10'); setNpcDex('50'); setNpcMov('7');
        setNpcWeapon(''); setNpcDamage('1d3'); setNpcSkill('');
        onEncounterConfirmed();
      } finally {
        setNpcCreating(false);
      }
    };

    const renderParticipant = (p: Participant) => (
      <div
        key={p.characterId}
        className={`bh-encounter-participant ${p.side === 'enemy' ? 'bh-encounter-participant--enemy' : ''} ${p.actedThisRound ? 'bh-encounter-participant--acted' : ''}`}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <strong>{p.displayName || p.display_name || (p.characterId.startsWith('npc:') ? p.characterId.slice(4, 10) : p.characterId.slice(0, 6))}</strong>
          <span style={{ fontSize: 10, opacity: 0.6 }}>{p.side === 'player' ? '我方' : '敌方'}</span>
        </div>
        {/* HP Bar */}
        <div className="bh-stat-bar" style={{ marginTop: 4 }}>
          <span style={{ fontSize: 10 }}>HP</span>
          <div className="bh-stat-track">
            <div
              className={`bh-stat-fill${p.hp <= p.hpMax * 0.3 ? ' bh-stat-fill--red' : ''}`}
              style={{ width: `${p.hpMax > 0 ? Math.max(0, (p.hp / p.hpMax) * 100) : 0}%` }}
            />
          </div>
          <span style={{ fontSize: 10 }}>{p.hp}/{p.hpMax}</span>
        </div>
        {p.statusTags.length > 0 && (
          <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            {p.statusTags.map((tag) => (
              <span key={tag} className="bh-eyebrow" style={{ fontSize: 8, padding: '1px 4px' }}>
                {tag}
              </span>
            ))}
          </div>
        )}
        {activeEncounter.type === 'chase' && (
          <div style={{ marginTop: 4, fontSize: 10 }}>
            距离: <strong>{p.distanceBand}</strong> | MOV: {p.mov}
          </div>
        )}
      </div>
    );

    return (
      <section className="bh-panel bh-encounter-active">
        <span className="bh-eyebrow">
          {activeEncounter.type === 'combat' ? 'COMBAT / 战斗' : 'CHASE / 追逐'}
        </span>
        <h2 className="bh-panel-title">
          第 {activeEncounter.currentRound} 回合
          {activeEncounter.summary && <span style={{ fontSize: 11, marginLeft: 8 }}>— {activeEncounter.summary}</span>}
        </h2>

        {/* Distance bar for chase */}
        {activeEncounter.type === 'chase' && (
          <div className="bh-encounter-distance-bar">
            {['engaged', 'near', 'short', 'medium', 'long', 'escaped'].map((band) => {
              const atBand = activeEncounter.participants.filter((p) => p.distanceBand === band);
              return (
                <div
                  key={band}
                  className={`bh-encounter-distance-band ${atBand.length > 0 ? 'bh-encounter-distance-band--current' : ''}`}
                >
                  <span>{band}</span>
                  {atBand.length > 0 && <small>{atBand.length}人</small>}
                </div>
              );
            })}
          </div>
        )}

        {/* Player participants */}
        {playerParts.length > 0 && (
          <>
            <h3 style={{ marginTop: 12, fontSize: 13 }}>我方</h3>
            <div className="bh-encounter-grid">{playerParts.map(renderParticipant)}</div>
          </>
        )}

        {/* Enemy participants */}
        {enemyParts.length > 0 && (
          <>
            <h3 style={{ marginTop: 12, fontSize: 13 }}>敌方</h3>
            <div className="bh-encounter-grid">{enemyParts.map(renderParticipant)}</div>
          </>
        )}

        {neutralParts.length > 0 && (
          <>
            <h3 style={{ marginTop: 12, fontSize: 13 }}>中立</h3>
            <div className="bh-encounter-grid">{neutralParts.map(renderParticipant)}</div>
          </>
        )}

        {/* Quick NPC Creator */}
        <details style={{ marginTop: 12 }}>
          <summary className="bh-eyebrow" style={{ cursor: 'pointer' }}>+ 快速创建 NPC</summary>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginTop: 8 }}>
            <input className="bh-input" placeholder="名称" value={npcName} onChange={(e) => setNpcName(e.target.value)} />
            <input className="bh-input" placeholder="HP" type="number" value={npcHp} onChange={(e) => setNpcHp(e.target.value)} />
            <input className="bh-input" placeholder="DEX" type="number" value={npcDex} onChange={(e) => setNpcDex(e.target.value)} />
            <input className="bh-input" placeholder="MOV" type="number" value={npcMov} onChange={(e) => setNpcMov(e.target.value)} />
            <input className="bh-input" placeholder="武器名" value={npcWeapon} onChange={(e) => setNpcWeapon(e.target.value)} />
            <input className="bh-input" placeholder="伤害 (如 1d6)" value={npcDamage} onChange={(e) => setNpcDamage(e.target.value)} />
            <input className="bh-input" placeholder="主要技能" value={npcSkill} onChange={(e) => setNpcSkill(e.target.value)} style={{ gridColumn: '1 / -1' }} />
            <button
              className="bh-button bh-button--black"
              onClick={handleCreateNpc}
              disabled={npcCreating}
              style={{ gridColumn: '1 / -1' }}
            >
              {npcCreating ? '创建中...' : '创建 NPC'}
            </button>
          </div>
        </details>

        {/* Host Actions */}
        <div style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button className="bh-button bh-button--yellow" onClick={handleNextRound}>
            下一回合
          </button>
          <button className="bh-button bh-button--red" onClick={handleResolve}>
            强制结束
          </button>
        </div>
      </section>
    );
  }

  // ── No Encounter State ──
  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">CHASE / COMBAT</span>
      <h2 className="bh-panel-title">战斗追踪器</h2>
      <div className="bh-skeleton-row">
        <strong>当前状态</strong>
        <span>等待主持人开启冲突场景</span>
      </div>
    </section>
  );
}
