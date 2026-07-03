import { useState, useEffect } from 'react';
import { apiFetch, authHeaders } from '../api';
import { BrutalProgress } from '../components/BauhausShell';
import { getSlotValue } from '../shared/identity';
import { CATEGORY_META, getSkillDef, getDifficultyThresholds } from '../data/coc7e-skills';
import type { CharacterSheet, SkillCheckResult } from '../types';
import type { SkillCategory } from '../data/coc7e-skills';

interface EnrichedSkill {
  name: string;
  value: number;
  base: number;
  category: SkillCategory;
  description: string;
}

type SuccessLevel = 'critical' | 'extreme' | 'hard' | 'regular' | 'failure' | 'fumble';

const SUCCESS_LEVELS: Record<SuccessLevel, { label: string; cssClass: string }> = {
  critical: { label: '大成功!', cssClass: 'bh-roll--critical' },
  extreme:  { label: '极难成功', cssClass: 'bh-roll--extreme' },
  hard:     { label: '困难成功', cssClass: 'bh-roll--hard' },
  regular:  { label: '常规成功', cssClass: 'bh-roll--regular' },
  failure:  { label: '失败', cssClass: 'bh-roll--failure' },
  fumble:   { label: '大失败!', cssClass: 'bh-roll--fumble' },
};

interface PlayerCharacterProps {
  externalResult?: SkillCheckResult | null;
  onResultConsumed?: () => void;
}

export default function PlayerCharacter({ externalResult, onResultConsumed }: PlayerCharacterProps) {
  const [char, setChar] = useState<CharacterSheet | null>(null);
  const [activeSkill, setActiveSkill] = useState<EnrichedSkill | null>(null);
  const [showAllSkills, setShowAllSkills] = useState(false);
  const [checkResult, setCheckResult] = useState<SkillCheckResult | null>(null);
  const [checking, setChecking] = useState<string | null>(null);

  // Merge external WS result with local fallback result
  const displayResult = externalResult || checkResult;

  // When external result arrives, clear checking state and consume
  useEffect(() => {
    if (externalResult) {
      setChecking(null);
      if (onResultConsumed) onResultConsumed();
    }
  }, [externalResult, onResultConsumed]);

  useEffect(() => {
    apiFetch<CharacterSheet>('/api/player/character', { headers: authHeaders() })
      .then(setChar)
      .catch(() => {});
  }, []);

  // Enrich character skills with dictionary data, group by category
  const enrichedByCategory = (): Partial<Record<SkillCategory, EnrichedSkill[]>> => {
    if (!char?.skills) return {};
    const entries = Object.entries(char.skills);
    const groups: Partial<Record<SkillCategory, EnrichedSkill[]>> = {};
    for (const [name, value] of entries) {
      const def = getSkillDef(name);
      const category = def?.category ?? 'other';
      const base = def?.base ?? 0;
      const description = def?.description ?? '';
      if (!groups[category]) groups[category] = [];
      groups[category]!.push({ name, value, base, category, description });
    }
    // Sort each category: non-zero first (desc), then zero (alpha)
    for (const cat of Object.keys(groups) as SkillCategory[]) {
      groups[cat]!.sort((a, b) => {
        if (a.value > 0 && b.value === 0) return -1;
        if (a.value === 0 && b.value > 0) return 1;
        if (a.value !== b.value) return b.value - a.value;
        return a.name.localeCompare(b.name);
      });
    }
    return groups;
  };

  /** Submit skill check via the main intent pipeline, fallback to standalone check. */
  const submitSkillCheck = async (skillName: string, skillValue: number) => {
    if (checking) return;
    setChecking(skillName);
    setCheckResult(null);
    const actionId = crypto.randomUUID();
    try {
      const res = await fetch('/api/player/intent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Room-Token': getSlotValue('player_token') || '',
        },
        body: JSON.stringify({
          action_id: actionId,
          intent_type: 'skill_check',
          declared_intent: `使用技能：${skillName}`,
          params: { skillName, skillValue, difficulty: 'regular' },
        }),
      });
      if (!res.ok) throw new Error('intent pipeline unavailable');
      // Result will arrive via WebSocket in parent — keep checking state
    } catch {
      // Fallback: standalone skill check
      try {
        const result = await apiFetch<SkillCheckResult>('/api/player/skill-check', {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify({ skill_name: skillName, skill_value: skillValue }),
        });
        setCheckResult(result);
      } catch { /* ignore */ }
    } finally {
      setChecking(null);
    }
  };

  // ------ RENDER ------

  if (!char) {
    return (
      <section className="bh-panel">
        <p style={{ textAlign: 'center', color: 'var(--bh-muted)', margin: '40px 0' }}>加载角色数据中...</p>
      </section>
    );
  }

  const grouped = enrichedByCategory();
  const categoryOrder: SkillCategory[] = ['investigation', 'social', 'knowledge', 'action', 'combat', 'other'];
  const hasZeroSkills = categoryOrder.some(
    (cat) => grouped[cat]?.some((s) => s.value === 0),
  );

  const displayName = char.investigator_name || char.name || '未命名调查员';
  const subtitle = [char.player_name ? `玩家：${char.player_name}` : null, char.occupation ? `职业：${char.occupation}` : null]
    .filter(Boolean).join(' / ');

  return (
    <div>
      {/* --- Vitals --- */}
      <section className="bh-panel" style={{ marginBottom: 16 }}>
        <span className="bh-eyebrow">INVESTIGATOR</span>
        <h2 className="bh-panel-title">{displayName}</h2>
        {subtitle && (
          <p style={{ margin: '0 0 14px', color: 'var(--bh-muted)', fontWeight: 800, fontSize: 13 }}>
            {subtitle}
          </p>
        )}

        <div className="bh-vitals-grid">
          <BrutalProgress label="HP" value={char.hp} max={char.max_hp} tone="red" />
          <BrutalProgress label="SAN" value={char.san} max={char.max_san} tone="red" />
          <div className="bh-stat-bar">
            <strong>MP</strong>
            <div className="bh-stat-track">
              <div className="bh-stat-fill" style={{ width: `${char.max_mp > 0 ? (char.mp / char.max_mp) * 100 : 0}%`, background: 'var(--bh-blue)' }} />
              <span className="bh-stat-value">{char.mp}/{char.max_mp}</span>
            </div>
          </div>
          <div className="bh-stat-bar">
            <strong>LUCK</strong>
            <div className="bh-stat-track">
              <div className="bh-stat-fill" style={{ width: `${char.luck}%`, background: 'var(--bh-yellow-dim)' }} />
              <span className="bh-stat-value">{char.luck}</span>
            </div>
          </div>
        </div>
      </section>

      {/* --- Background --- */}
      {char.background && (
        <section className="bh-panel" style={{ marginBottom: 16 }}>
          <span className="bh-eyebrow">BACKGROUND</span>
          <p style={{ margin: 0, fontWeight: 700, lineHeight: 1.6 }}>{char.background}</p>
        </section>
      )}

      {/* --- Active Skill Detail --- */}
      {activeSkill && (
        <section className="bh-skill-detail">
          <div className="bh-skill-detail-header">
            <span className="bh-eyebrow">{CATEGORY_META[activeSkill.category].label}</span>
            <button className="bh-button" onClick={() => setActiveSkill(null)}>← 返回列表</button>
          </div>
          <h3 className="bh-panel-title" style={{ marginTop: 12 }}>{activeSkill.name}</h3>
          <div className="bh-skill-detail-meta">
            <span>基础值：<strong>{activeSkill.base}%</strong></span>
            <span>当前值：<strong>{activeSkill.value}%</strong></span>
          </div>
          {activeSkill.description && (
            <p className="bh-skill-desc">{activeSkill.description}</p>
          )}

          <div className="bh-threshold-table">
            {(['regular', 'hard', 'extreme'] as const).map((level) => {
              const t = getDifficultyThresholds(activeSkill.value);
              const labels = { regular: '常规', hard: '困难', extreme: '极难' };
              return (
                <div key={level} className="bh-threshold-cell">
                  <span className="bh-eyebrow" style={{ fontSize: 10 }}>{labels[level]}</span>
                  <strong>{t[level]}</strong>
                </div>
              );
            })}
          </div>

          <button
            className="bh-button bh-button--yellow"
            style={{ width: '100%', marginTop: 12 }}
            disabled={checking !== null}
            onClick={() => submitSkillCheck(activeSkill.name, activeSkill.value)}
          >
            {checking === activeSkill.name ? '检定中...' : '发起检定'}
          </button>

          {displayResult && displayResult.skill_name === activeSkill.name && (
            <RollResult result={displayResult} />
          )}
        </section>
      )}

      {/* --- Skills by Category --- */}
      {!activeSkill && (
        <section className="bh-panel">
          <span className="bh-eyebrow">SKILLS</span>
          <h2 className="bh-panel-title">技能列表</h2>

          {categoryOrder.map((cat) => {
            const skills = grouped[cat];
            if (!skills || skills.length === 0) return null;
            const visible = showAllSkills ? skills : skills.filter((s) => s.value > 0);
            if (visible.length === 0) return null;
            const meta = CATEGORY_META[cat];

            return (
              <div key={cat} className="bh-skill-category">
                <h3 className="bh-skill-cat-title">
                  <span className="bh-eyebrow" style={{ fontSize: 10 }}>{meta.enLabel}</span>
                  {' '}{meta.label}
                </h3>
                <div className="bh-skill-grid">
                  {visible.map((skill) => (
                    <button
                      key={skill.name}
                      className="bh-skill-chip"
                      onClick={() => setActiveSkill(skill)}
                    >
                      <span className="bh-skill-chip-name">{skill.name}</span>
                      <span className="bh-skill-chip-value">{skill.value}%</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })}

          {hasZeroSkills && (
            <div className="bh-toggle-row">
              <button
                className="bh-button bh-button--blue"
                onClick={() => setShowAllSkills(!showAllSkills)}
              >
                {showAllSkills ? '收起' : '显示全部技能（含未获得）'}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Standalone roll result (when no detail panel is open) */}
      {displayResult && !activeSkill && (
        <section style={{ marginTop: 16 }}>
          <RollResult result={displayResult} />
        </section>
      )}
    </div>
  );
}

/** Inline roll result display. */
function RollResult({ result }: { result: SkillCheckResult }) {
  const level = result.success_level as SuccessLevel;
  const meta = SUCCESS_LEVELS[level] ?? { label: level, cssClass: '' };
  return (
    <div className={`bh-roll-result ${meta.cssClass}`}>
      <div className="bh-roll-header">
        <strong>{result.skill_name} 检定</strong>
      </div>
      <div className="bh-roll-numbers">
        <span>掷骰：<strong>{result.roll}</strong></span>
        <span>阈值：<strong>{result.skill_value}</strong></span>
      </div>
      <div className="bh-roll-level">{meta.label}</div>
      {result.detail && <p className="bh-roll-detail">{result.detail}</p>}
    </div>
  );
}
