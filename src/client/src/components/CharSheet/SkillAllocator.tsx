import { useState } from 'react';
import { SKILLS, OCCUPATIONS, CATEGORY_META } from '../../data/coc7e-skills';
import type { SkillCategory } from '../../data/coc7e-skills';

export function getSkillAllocationIncrement(remaining: number): number {
  return Math.min(5, Math.max(0, remaining));
}

interface Props {
  attributes: { str: number; con: number; siz: number; dex: number; app: number; int: number; pow: number; edu: number; luck: number };
  occupationId: string;
  onComplete: (skills: Record<string, number>, occupation: string) => void;
}

export default function SkillAllocator({ attributes, occupationId, onComplete }: Props) {
  const occupation = OCCUPATIONS.find((o) => o.id === occupationId) || OCCUPATIONS[0];

  const [phase, setPhase] = useState<'occupation' | 'interest'>('occupation');

  const calcOccupationPoints = (): number => {
    const [a1, a2, a3] = occupation.skillPoints;
    const getVal = (k: string) => {
      const map: Record<string, number> = { edu: attributes.edu, str: attributes.str, con: attributes.con, siz: attributes.siz, dex: attributes.dex, app: attributes.app, int: attributes.int, pow: attributes.pow };
      return map[k] ?? 0;
    };
    return getVal(a1) * 2 + getVal(a2) + getVal(a3);
  };

  const interestPoints = attributes.int * 2;

  const [occAlloc, setOccAlloc] = useState<Record<string, number>>({});
  const [intAlloc, setIntAlloc] = useState<Record<string, number>>({});

  const occTotal = calcOccupationPoints();
  const occUsed = Object.values(occAlloc).reduce((a, b) => a + b, 0);
  const occRemaining = occTotal - occUsed;

  const intUsed = Object.values(intAlloc).reduce((a, b) => a + b, 0);
  const intRemaining = interestPoints - intUsed;

  const getSkillBase = (name: string): number => {
    if (name === '闪避') return Math.floor(attributes.dex / 2);
    if (name === '母语') return attributes.edu;
    const skill = SKILLS.find((s) => s.name === name);
    return skill?.base ?? 0;
  };

  const setOccSkill = (name: string, val: number) => {
    const clamped = Math.max(0, Math.min(val, 99 - getSkillBase(name)));
    setOccAlloc((prev) => ({ ...prev, [name]: clamped }));
  };

  const setIntSkill = (name: string, val: number) => {
    const clamped = Math.max(0, Math.min(val, 99 - getSkillBase(name) - (occAlloc[name] || 0)));
    setIntAlloc((prev) => ({ ...prev, [name]: clamped }));
  };

  const occSkills = occupation.skills;
  const intSkills = SKILLS.filter((s) => !occSkills.includes(s.name)).map((s) => s.name);

  // Group interest skills by category for display
  const intByCategory = (): Partial<Record<SkillCategory, string[]>> => {
    const groups: Partial<Record<SkillCategory, string[]>> = {};
    for (const name of intSkills) {
      const def = SKILLS.find((s) => s.name === name);
      const cat = def?.category ?? 'other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat]!.push(name);
    }
    return groups;
  };

  const confirm = () => {
    const final: Record<string, number> = {};
    for (const s of SKILLS) {
      const base = getSkillBase(s.name);
      const occ = occAlloc[s.name] || 0;
      const int_ = intAlloc[s.name] || 0;
      const val = base + occ + int_;
      if (val > 0) final[s.name] = val;
    }
    final['闪避'] = Math.floor(attributes.dex / 2) + (occAlloc['闪避'] || 0) + (intAlloc['闪避'] || 0);
    final['母语'] = attributes.edu + (occAlloc['母语'] || 0) + (intAlloc['母语'] || 0);
    onComplete(final, occupation.name);
  };

  const categoryOrder: SkillCategory[] = ['investigation', 'social', 'knowledge', 'action', 'combat', 'other'];

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">SKILL POINTS</span>
      <h2 className="bh-panel-title">
        {phase === 'occupation' ? '职业技能点分配' : '兴趣技能点分配'}
      </h2>

      <div className="bh-skill-points-info">
        <span><strong>职业：</strong>{occupation.name}</span>
        {phase === 'occupation' ? (
          <span><strong>剩余职业点数：</strong><span style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontSize: 20 }}>{occRemaining}</span> / {occTotal}</span>
        ) : (
          <span><strong>剩余兴趣点数：</strong><span style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontSize: 20 }}>{intRemaining}</span> / {interestPoints}</span>
        )}
      </div>

      <div className="bh-source-toggle" style={{ marginBottom: 16 }}>
        <button
          className={`bh-button ${phase === 'occupation' ? 'bh-button--yellow' : ''}`}
          onClick={() => setPhase('occupation')}
        >
          职业技能
        </button>
        <button
          className={`bh-button ${phase === 'interest' ? 'bh-button--yellow' : ''}`}
          onClick={() => setPhase('interest')}
        >
          兴趣技能
        </button>
      </div>

      {phase === 'occupation' && (
        <div>
          {occSkills.map((name) => {
            const base = getSkillBase(name);
            const alloc = occAlloc[name] || 0;
            return (
              <SkillRow
                key={name} name={name} base={base} alloc={alloc}
                remaining={occRemaining} onChange={(v) => setOccSkill(name, v)}
              />
            );
          })}
          {occRemaining > 0 && (
            <p style={{ color: 'var(--bh-muted)', fontWeight: 800, fontSize: 13, marginTop: 8 }}>
              还有 {occRemaining} 点可分配（职业点数按职业规定的属性计算）
            </p>
          )}
        </div>
      )}

      {phase === 'interest' && (
        <div>
          {categoryOrder.map((cat) => {
            const names = intByCategory()[cat];
            if (!names || names.length === 0) return null;
            const meta = CATEGORY_META[cat];
            return (
              <div key={cat} style={{ marginBottom: 16 }}>
                <h3 style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontSize: 13, fontWeight: 900, margin: '0 0 6px' }}>
                  {meta.label}
                </h3>
                {names.map((name) => {
                  const base = getSkillBase(name);
                  const occ = occAlloc[name] || 0;
                  const alloc = intAlloc[name] || 0;
                  return (
                    <SkillRow
                      key={name} name={name} base={base + occ} alloc={alloc}
                      remaining={intRemaining} onChange={(v) => setIntSkill(name, v)}
                    />
                  );
                })}
              </div>
            );
          })}
        </div>
      )}

      {phase === 'interest' && intRemaining <= 0 && (
        <button className="bh-button bh-button--yellow" style={{ width: '100%', marginTop: 16 }} onClick={confirm}>
          确认技能分配，进入背景编辑
        </button>
      )}
    </section>
  );
}

function SkillRow({ name, base, alloc, remaining, onChange }: {
  name: string; base: number; alloc: number; remaining: number; onChange: (v: number) => void;
}) {
  const increment = getSkillAllocationIncrement(remaining);

  return (
    <div className="bh-alloc-row">
      <span className="bh-alloc-name">{name}</span>
      <span className="bh-alloc-base">{base}%</span>
      <span style={{ color: 'var(--bh-muted)' }}>+</span>
      <button className="bh-alloc-btn" onClick={() => onChange(alloc - 5)} disabled={alloc <= 0}>−5</button>
      <span className="bh-alloc-curr">{alloc}</span>
      <button className="bh-alloc-btn" onClick={() => onChange(alloc + increment)} disabled={remaining <= 0}>+5</button>
      <span className="bh-alloc-total">{base + alloc}%</span>
    </div>
  );
}
