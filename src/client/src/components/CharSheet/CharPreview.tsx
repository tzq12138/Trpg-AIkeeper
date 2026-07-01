import { CATEGORY_META, SKILLS } from '../../data/coc7e-skills';
import type { SkillCategory } from '../../data/coc7e-skills';

export interface PreviewData {
  name: string;
  age: number;
  gender: string;
  occupation: string;
  attributes: { str: number; con: number; siz: number; dex: number; app: number; int: number; pow: number; edu: number; luck: number };
  derived: { hp: number; mp: number; san: number; mov: number; db: string; build: number };
  skills: Record<string, number>;
  background: { description: string; belief: string; importantPerson: string; valuableThing: string; trait: string; wound: string; phobia: string };
}

interface Props {
  data: PreviewData;
  onConfirm: () => void;
  onBack: () => void;
}

const ATTR_LABELS: Record<string, string> = {
  str: '力量', con: '体质', siz: '体型', dex: '敏捷',
  app: '外貌', int: '智力', pow: '意志', edu: '教育', luck: '幸运',
};

export default function CharPreview({ data, onConfirm, onBack }: Props) {
  const categoryOrder: SkillCategory[] = ['investigation', 'social', 'knowledge', 'action', 'combat', 'other'];

  // Group & sort skills by category
  const skillsByCat = (): Partial<Record<SkillCategory, Array<{ name: string; value: number }>>> => {
    const groups: Partial<Record<SkillCategory, Array<{ name: string; value: number }>>> = {};
    for (const [name, value] of Object.entries(data.skills)) {
      if (value <= 0) continue;
      const def = SKILLS.find((s) => s.name === name);
      const cat = def?.category ?? 'other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat]!.push({ name, value });
    }
    for (const cat of Object.keys(groups) as SkillCategory[]) {
      groups[cat]!.sort((a, b) => b.value - a.value);
    }
    return groups;
  };

  const bg = data.background;
  const hasBg = bg.description || bg.belief || bg.importantPerson || bg.valuableThing || bg.trait || bg.wound || bg.phobia;

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">PREVIEW</span>
      <h2 className="bh-panel-title">角色卡预览</h2>

      {/* Identity */}
      <div className="bh-preview-box" style={{ padding: 14 }}>
        <h3 style={{ margin: 0, fontSize: 22 }}>{data.name}</h3>
        <p style={{ margin: '4px 0 0' }}>
          {data.occupation} | {data.age}岁 | {data.gender || '未设定'}
        </p>
      </div>

      {/* Attributes */}
      <div style={{ marginBottom: 16 }}>
        <span className="bh-eyebrow" style={{ fontSize: 10 }}>ATTRIBUTES</span>
        <div className="bh-attr-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
          {Object.entries(data.attributes).map(([k, v]) => (
            <div key={k} className="bh-attr-card" style={{ padding: '8px 6px' }}>
              <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--bh-muted)' }}>{ATTR_LABELS[k] || k.toUpperCase()}</span>
              <strong style={{ fontSize: 22, fontFamily: '"Space Grotesk", Impact, sans-serif' }}>{v}</strong>
            </div>
          ))}
        </div>
      </div>

      {/* Derived Stats */}
      <div style={{ marginBottom: 16 }}>
        <span className="bh-eyebrow" style={{ fontSize: 10 }}>DERIVED</span>
        <div className="bh-attr-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)' }}>
          <DerivedBox label="HP" value={`${data.derived.hp}`} />
          <DerivedBox label="MP" value={`${data.derived.mp}`} />
          <DerivedBox label="SAN" value={`${data.derived.san}`} />
          <DerivedBox label="MOV" value={`${data.derived.mov}`} />
          <DerivedBox label="DB" value={data.derived.db} />
          <DerivedBox label="BUILD" value={`${data.derived.build >= 0 ? '+' : ''}${data.derived.build}`} />
        </div>
      </div>

      {/* Skills */}
      <div style={{ marginBottom: 16 }}>
        <span className="bh-eyebrow" style={{ fontSize: 10 }}>SKILLS</span>
        <div className="bh-skill-grid" style={{ gridTemplateColumns: '1fr' }}>
          {categoryOrder.map((cat) => {
            const skills = skillsByCat()[cat];
            if (!skills || skills.length === 0) return null;
            const meta = CATEGORY_META[cat];
            return (
              <div key={cat} style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: 12, padding: '2px 0', display: 'block', borderBottom: '3px solid var(--bh-black)' }}>
                  {meta.label}
                </strong>
                {skills.map((s) => (
                  <div key={s.name} className="bh-skill-row" style={{ padding: '4px 0', borderBottom: '2px solid var(--bh-paper-3)' }}>
                    <span style={{ fontWeight: 800 }}>{s.name}</span>
                    <span style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontWeight: 900 }}>{s.value}%</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* Background */}
      {hasBg && (
        <div style={{ marginBottom: 16 }}>
          <span className="bh-eyebrow" style={{ fontSize: 10 }}>BACKGROUND</span>
          <div className="bh-preview-box" style={{ padding: 14, gap: 6 }}>
            {bg.description && <p style={{ margin: 0, fontWeight: 700 }}><strong>描述：</strong>{bg.description}</p>}
            {bg.belief && <p style={{ margin: 0, fontWeight: 700 }}><strong>信念：</strong>{bg.belief}</p>}
            {bg.importantPerson && <p style={{ margin: 0, fontWeight: 700 }}><strong>重要之人：</strong>{bg.importantPerson}</p>}
            {bg.valuableThing && <p style={{ margin: 0, fontWeight: 700 }}><strong>宝贵之物：</strong>{bg.valuableThing}</p>}
            {bg.trait && <p style={{ margin: 0, fontWeight: 700 }}><strong>特质：</strong>{bg.trait}</p>}
            {bg.wound && <p style={{ margin: 0, fontWeight: 700 }}><strong>伤疤：</strong>{bg.wound}</p>}
            {bg.phobia && <p style={{ margin: 0, fontWeight: 700 }}><strong>恐惧症：</strong>{bg.phobia}</p>}
          </div>
        </div>
      )}

      <div className="bh-action-row">
        <button className="bh-button" onClick={onBack}>返回修改</button>
        <button className="bh-button bh-button--yellow" onClick={onConfirm}>确认创建角色</button>
      </div>
    </section>
  );
}

function DerivedBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="bh-attr-card" style={{ padding: '8px 6px', borderColor: 'var(--bh-yellow-dim)' }}>
      <span style={{ fontSize: 10, fontWeight: 800, color: 'var(--bh-muted)' }}>{label}</span>
      <strong style={{ fontSize: 20, fontFamily: '"Space Grotesk", Impact, sans-serif' }}>{value}</strong>
    </div>
  );
}
