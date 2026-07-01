import { useState } from 'react';
import { rollAttribute, calcHP, calcMP, calcMOV, calcDBBuild } from '../../data/coc7e-skills';

export interface Attributes {
  str: number; con: number; siz: number; dex: number;
  app: number; int: number; pow: number; edu: number; luck: number;
}

export interface DerivedStats {
  hp: number; mp: number; san: number; mov: number; db: string; build: number;
}

interface Props {
  onComplete: (attrs: Attributes, derived: DerivedStats) => void;
}

const ATTR_DEFS: { key: keyof Omit<Attributes, 'luck'>; label: string; enLabel: string; type: '3d6' | '2d6+6' }[] = [
  { key: 'str', label: '力量', enLabel: 'STR', type: '3d6' },
  { key: 'con', label: '体质', enLabel: 'CON', type: '3d6' },
  { key: 'siz', label: '体型', enLabel: 'SIZ', type: '2d6+6' },
  { key: 'dex', label: '敏捷', enLabel: 'DEX', type: '3d6' },
  { key: 'app', label: '外貌', enLabel: 'APP', type: '3d6' },
  { key: 'int', label: '智力', enLabel: 'INT', type: '2d6+6' },
  { key: 'pow', label: '意志', enLabel: 'POW', type: '3d6' },
  { key: 'edu', label: '教育', enLabel: 'EDU', type: '2d6+6' },
];

export default function AttributeRoller({ onComplete }: Props) {
  const [results, setResults] = useState<Record<string, { dice: number[]; value: number }>>({});
  const [luckAttempts, setLuckAttempts] = useState<number[][]>([]);
  const [bestLuck, setBestLuck] = useState(0);
  const [phase, setPhase] = useState<'attrs' | 'luck' | 'done'>('attrs');

  const rollAll = () => {
    const newResults: Record<string, { dice: number[]; value: number }> = {};
    for (const attr of ATTR_DEFS) {
      newResults[attr.key] = rollAttribute(attr.type);
    }
    setResults(newResults);
  };

  const reroll = (key: string, type: '3d6' | '2d6+6') => {
    setResults((prev) => ({ ...prev, [key]: rollAttribute(type) }));
  };

  const rollLuckFn = () => {
    const attempts: number[][] = [];
    let best = 0;
    for (let i = 0; i < 3; i++) {
      const dice = Array.from({ length: 3 }, () => Math.floor(Math.random() * 6) + 1);
      const value = dice.reduce((a, b) => a + b, 0) * 5;
      attempts.push(dice);
      if (value > best) best = value;
    }
    setLuckAttempts(attempts);
    setBestLuck(best);
  };

  const confirm = () => {
    const attrs: Attributes = {
      str: results.str?.value ?? 50,
      con: results.con?.value ?? 50,
      siz: results.siz?.value ?? 60,
      dex: results.dex?.value ?? 50,
      app: results.app?.value ?? 50,
      int: results.int?.value ?? 60,
      pow: results.pow?.value ?? 50,
      edu: results.edu?.value ?? 60,
      luck: bestLuck,
    };
    const hp = calcHP(attrs.con, attrs.siz);
    const mp = calcMP(attrs.pow);
    const san = attrs.pow;
    const mov = calcMOV(attrs.str, attrs.dex, attrs.siz, 25);
    const { db, build } = calcDBBuild(attrs.str, attrs.siz);
    onComplete(attrs, { hp, mp, san, mov, db, build });
  };

  const allRolled = Object.keys(results).length === 8;

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">ATTRIBUTES</span>
      <h2 className="bh-panel-title">属性掷骰</h2>
      <p style={{ color: 'var(--bh-muted)', fontWeight: 800, fontSize: 13, marginTop: 0 }}>
        {phase === 'attrs' ? 'COC 7e 标准属性生成：3D6×5 或 (2D6+6)×5' : phase === 'luck' ? '幸运值：3 次掷骰取最高值' : '确认属性，进入下一步'}
      </p>

      {!allRolled && phase === 'attrs' && (
        <button className="bh-button bh-button--yellow" onClick={rollAll} style={{ marginBottom: 16 }}>
          一键掷骰全部属性
        </button>
      )}

      {allRolled && (
        <div className="bh-attr-grid">
          {ATTR_DEFS.map((attr) => {
            const r = results[attr.key];
            return (
              <div key={attr.key} className="bh-attr-card">
                <div className="bh-attr-card-header">
                  <span className="bh-eyebrow" style={{ fontSize: 9, padding: '3px 6px' }}>{attr.enLabel}</span>
                  <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--bh-muted)' }}>
                    {attr.type === '3d6' ? '3D6×5' : '(2D6+6)×5'}
                  </span>
                </div>
                <strong className="bh-attr-value">{r?.value ?? '?'}</strong>
                {r && (
                  <>
                    <span className="bh-attr-dice">({r.dice.join(' + ')})</span>
                    <button className="bh-attr-reroll" onClick={() => reroll(attr.key, attr.type)}>重掷</button>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}

      {allRolled && phase === 'attrs' && (
        <div style={{ marginTop: 20, textAlign: 'center' }}>
          <button className="bh-button bh-button--yellow" onClick={() => { rollLuckFn(); setPhase('luck'); }}>
            掷幸运值（3次取最高）
          </button>
        </div>
      )}

      {phase === 'luck' && luckAttempts.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div className="bh-luck-grid">
            {luckAttempts.map((dice, i) => {
              const val = dice.reduce((a, b) => a + b, 0) * 5;
              return (
                <div key={i} className="bh-attr-card">
                  <strong style={{ fontSize: 11 }}>第 {i + 1} 次</strong>
                  <span className="bh-attr-dice">({dice.join(' + ')})</span>
                  <strong className="bh-attr-value" style={{ fontSize: 28 }}>{val}</strong>
                </div>
              );
            })}
          </div>
          <p style={{ textAlign: 'center', margin: '12px 0', fontSize: 18, fontWeight: 900 }}>
            最终幸运值: <span style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontSize: 26, color: 'var(--bh-yellow-dim)' }}>{bestLuck}</span>
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'center' }}>
            <button className="bh-button" onClick={rollLuckFn}>重新掷骰</button>
            <button className="bh-button bh-button--yellow" onClick={() => setPhase('done')}>确认幸运值</button>
          </div>
        </div>
      )}

      {phase === 'done' && allRolled && (
        <div style={{ marginTop: 20 }}>
          <div className="bh-attr-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
            {ATTR_DEFS.map((a) => (
              <div key={a.key} className="bh-attr-card">
                <span className="bh-eyebrow" style={{ fontSize: 9, padding: '3px 6px' }}>{a.enLabel}</span>
                <span style={{ fontSize: 11, color: 'var(--bh-muted)', fontWeight: 800 }}>{a.label}</span>
                <strong className="bh-attr-value">{results[a.key]?.value}</strong>
              </div>
            ))}
            <div className="bh-attr-card">
              <span className="bh-eyebrow" style={{ fontSize: 9, padding: '3px 6px' }}>LUCK</span>
              <span style={{ fontSize: 11, color: 'var(--bh-muted)', fontWeight: 800 }}>幸运</span>
              <strong className="bh-attr-value">{bestLuck}</strong>
            </div>
          </div>
          <button className="bh-button bh-button--yellow" style={{ width: '100%', marginTop: 16 }} onClick={confirm}>
            确认属性，进入技能分配
          </button>
        </div>
      )}
    </section>
  );
}
