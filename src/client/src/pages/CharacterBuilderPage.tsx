import { useState } from 'react';
import AttributeRoller from '../components/CharSheet/AttributeRoller';
import SkillAllocator from '../components/CharSheet/SkillAllocator';
import BackgroundEditor from '../components/CharSheet/BackgroundEditor';
import CharPreview from '../components/CharSheet/CharPreview';
import { OCCUPATIONS, calcHP, calcMP, calcMOV, calcDBBuild } from '../data/coc7e-skills';
import type { Attributes, DerivedStats } from '../components/CharSheet/AttributeRoller';
import type { BackgroundData } from '../components/CharSheet/BackgroundEditor';
import type { PreviewData } from '../components/CharSheet/CharPreview';

type Step = 1 | 2 | 3 | 4 | 5;

export interface BuilderCharacterData {
  name: string;
  occupation: string;
  age: number;
  gender: string;
  attributes: Attributes;
  derived_stats: DerivedStats;
  skills: Record<string, number>;
  background: string;
  backstory: BackgroundData;
}

interface ScenarioTemplate {
  template_id: string; name: string; occupation: string; background: string;
  age: number; gender: string; attributes: Record<string, number>; skills: Record<string, number>;
}

interface Props {
  /** Called when builder completes with the final character data. */
  onComplete: (data: BuilderCharacterData) => void;
  /** Called when user wants to cancel/return. */
  onCancel: () => void;
  /** Optional scenario ID for fetching protagonist templates. */
  scenarioId?: string;
}

export default function CharacterBuilderPage({ onComplete, onCancel, scenarioId }: Props) {
  const [templates, setTemplates] = useState<ScenarioTemplate[]>([]);
  const [templatesLoaded, setTemplatesLoaded] = useState(false);

  // Fetch scenario templates if scenarioId is provided
  useState(() => {
    if (!scenarioId) { setTemplatesLoaded(true); return; }
    fetch(`/api/scenarios/${scenarioId}/templates`)
      .then((res) => (res.ok ? res.json() : []))
      .then((data: ScenarioTemplate[]) => setTemplates(data))
      .catch(() => {})
      .finally(() => setTemplatesLoaded(true));
  });
  // Step 1: Basic info
  const [name, setName] = useState('');
  const [age, setAge] = useState(25);
  const [gender, setGender] = useState('');
  const [occupationId, setOccupationId] = useState('detective');

  // Step 2-3: Attributes
  const [attributes, setAttributes] = useState<Attributes | null>(null);
  const [derivedStats, setDerivedStats] = useState<DerivedStats | null>(null);

  // Step 4-5: Skills
  const [skills, setSkills] = useState<Record<string, number> | null>(null);
  const [occupationName, setOccupationName] = useState('');

  // Step 6: Background
  const [backstory, setBackstory] = useState<BackgroundData | null>(null);

  const [step, setStep] = useState<Step>(1);

  const occupation = OCCUPATIONS.find((o) => o.id === occupationId) || OCCUPATIONS[0];

  const handleAttrComplete = (attrs: Attributes, derived: DerivedStats) => {
    setAttributes(attrs);
    setDerivedStats(derived);
    setStep(3);
  };

  const handleSkillComplete = (s: Record<string, number>, occName: string) => {
    setSkills(s);
    setOccupationName(occName);
    setStep(4);
  };

  const handleBgComplete = (bg: BackgroundData) => {
    setBackstory(bg);
    setStep(5);
  };

  const handleConfirm = () => {
    if (!attributes || !derivedStats || !skills || !backstory) return;
    const bgText = [
      backstory.description,
      backstory.belief ? `信念：${backstory.belief}` : '',
      backstory.importantPerson ? `重要之人：${backstory.importantPerson}` : '',
      backstory.valuableThing ? `宝贵之物：${backstory.valuableThing}` : '',
      backstory.trait ? `特质：${backstory.trait}` : '',
      backstory.wound ? `伤疤：${backstory.wound}` : '',
      backstory.phobia ? `恐惧症：${backstory.phobia}` : '',
    ].filter(Boolean).join('\n');

    onComplete({
      name,
      occupation: occupationName,
      age,
      gender,
      attributes,
      derived_stats: derivedStats,
      skills,
      background: bgText,
      backstory,
    });
  };

  const previewData: PreviewData | null = attributes && derivedStats && skills && backstory
    ? { name, age, gender, occupation: occupationName, attributes, derived: derivedStats, skills, background: backstory }
    : null;

  // Step indicator
  const stepLabels = ['基本信息', '属性掷骰', '技能分配', '背景故事', '角色预览'];
  const currentLabel = stepLabels[step - 1];

  return (
    <div style={{ maxWidth: 680, margin: '0 auto' }}>
      {/* Step indicator */}
      <div className="bh-step-indicator" style={{ marginBottom: 18 }}>
        <span className="bh-eyebrow">CHARACTER BUILDER</span>
        <div className="bh-step-dots">
          {stepLabels.map((label, i) => (
            <div key={i} className={`bh-step-dot ${i + 1 === step ? 'bh-step-dot--active' : ''} ${i + 1 < step ? 'bh-step-dot--done' : ''}`}>
              <span className="bh-step-num">{i + 1}</span>
              <span className="bh-step-label">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Step 1: Basic Info */}
      {step === 1 && (
        <section className="bh-panel">
          <span className="bh-eyebrow">STEP 1</span>
          <h2 className="bh-panel-title">基本信息</h2>

          {/* Scenario template quick-start */}
          {templates.length > 0 && (
            <div style={{ marginBottom: 18 }}>
              <span className="bh-eyebrow" style={{ fontSize: 10, padding: '3px 6px' }}>QUICK START</span>
              <div className="bh-preset-list" style={{ marginTop: 8 }}>
                {templates.map((tpl) => (
                  <button
                    key={tpl.template_id}
                    className="bh-preset-card"
                    type="button"
                    onClick={() => {
                      setName(tpl.name);
                      setOccupationId(
                        OCCUPATIONS.find((o) => o.name === tpl.occupation)?.id || 'ordinary',
                      );
                      setAge(tpl.age);
                      setGender(tpl.gender);
                      // Pre-fill attributes and skills if available
                      if (tpl.attributes && Object.keys(tpl.attributes).length > 0) {
                        setAttributes({
                          str: tpl.attributes.str || 50,
                          con: tpl.attributes.con || 50,
                          siz: tpl.attributes.siz || 60,
                          dex: tpl.attributes.dex || 50,
                          app: tpl.attributes.app || 50,
                          int: tpl.attributes.int || 60,
                          pow: tpl.attributes.pow || 50,
                          edu: tpl.attributes.edu || 60,
                          luck: tpl.attributes.luck || 50,
                        });
                        setDerivedStats({
                          hp: calcHP(tpl.attributes.con || 50, tpl.attributes.siz || 60),
                          mp: calcMP(tpl.attributes.pow || 50),
                          san: tpl.attributes.pow || 50,
                          mov: calcMOV(tpl.attributes.str || 50, tpl.attributes.dex || 50, tpl.attributes.siz || 60, tpl.age),
                          db: calcDBBuild(tpl.attributes.str || 50, tpl.attributes.siz || 60).db,
                          build: calcDBBuild(tpl.attributes.str || 50, tpl.attributes.siz || 60).build,
                        });
                      }
                      if (tpl.skills && Object.keys(tpl.skills).length > 0) {
                        setSkills(tpl.skills);
                        setOccupationName(tpl.occupation);
                      }
                      if (tpl.background) {
                        setBackstory({
                          description: tpl.background,
                          belief: '', importantPerson: '', valuableThing: '',
                          trait: '', wound: '', phobia: '',
                        });
                      }
                      setStep(2);
                    }}
                  >
                    <strong>{tpl.name}</strong>
                    <span>{tpl.occupation || '剧本角色'}</span>
                    <small>快速创建 →</small>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="bh-form" style={{ width: '100%' }}>
            <div className="bh-field">
              <label>调查员姓名</label>
              <input className="bh-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="你的角色叫什么？" />
            </div>
            <div className="bh-action-row">
              <div className="bh-field">
                <label>年龄</label>
                <input className="bh-input" type="number" value={age} min={15} max={90} onChange={(e) => setAge(Number(e.target.value) || 25)} />
              </div>
              <div className="bh-field">
                <label>性别</label>
                <input className="bh-input" value={gender} onChange={(e) => setGender(e.target.value)} placeholder="男 / 女 / 其他" />
              </div>
            </div>
            <div className="bh-field">
              <label>职业</label>
              <select className="bh-input" value={occupationId} onChange={(e) => setOccupationId(e.target.value)}>
                {OCCUPATIONS.map((o) => (
                  <option key={o.id} value={o.id}>{o.name}（信用 {o.creditMin}-{o.creditMax}）</option>
                ))}
              </select>
            </div>
            {occupation && (
              <div className="bh-preview-box" style={{ padding: 12 }}>
                <p style={{ margin: 0, fontWeight: 800, fontSize: 13 }}>
                  推荐技能：{occupation.skills.join('、')}
                </p>
                <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--bh-muted)', fontWeight: 700 }}>
                  职业点数计算：{occupation.skillPoints.map((s) => s.toUpperCase()).join('×2 + ')}
                  {occupation.skillPoints.length === 3 ? '' : ''}
                </p>
              </div>
            )}
          </div>
          <div className="bh-action-row" style={{ marginTop: 16 }}>
            <button className="bh-button" onClick={onCancel}>取消</button>
            <button className="bh-button bh-button--yellow" disabled={!name.trim()} onClick={() => setStep(2)}>
              下一步：属性掷骰
            </button>
          </div>
        </section>
      )}

      {/* Step 2: Attributes */}
      {step === 2 && <AttributeRoller onComplete={handleAttrComplete} />}

      {/* Step 3: Skills */}
      {step === 3 && attributes && (
        <div>
          <SkillAllocator attributes={attributes} occupationId={occupationId} onComplete={handleSkillComplete} />
          <div style={{ marginTop: 10 }}>
            <button className="bh-button" onClick={() => setStep(2)}>← 返回重新掷骰</button>
          </div>
        </div>
      )}

      {/* Step 4: Background */}
      {step === 4 && (
        <div>
          <BackgroundEditor onComplete={handleBgComplete} />
          <div style={{ marginTop: 10 }}>
            <button className="bh-button" onClick={() => setStep(3)}>← 返回调整技能</button>
          </div>
        </div>
      )}

      {/* Step 5: Preview & Confirm */}
      {step === 5 && previewData && (
        <CharPreview data={previewData} onConfirm={handleConfirm} onBack={() => setStep(4)} />
      )}
    </div>
  );
}
