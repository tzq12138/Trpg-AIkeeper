import { useState } from 'react';

export interface BackgroundData {
  description: string;
  belief: string;
  importantPerson: string;
  valuableThing: string;
  trait: string;
  wound: string;
  phobia: string;
}

interface Props {
  onComplete: (data: BackgroundData) => void;
}

const FIELDS: { key: keyof BackgroundData; label: string; placeholder: string }[] = [
  { key: 'description', label: '个人描述', placeholder: '外貌、穿着、举止特点...' },
  { key: 'belief', label: '思想 / 信念', placeholder: '人生信条、世界观...' },
  { key: 'importantPerson', label: '重要之人', placeholder: '对你最重要的人...' },
  { key: 'valuableThing', label: '宝贵之物', placeholder: '你最珍视的物品...' },
  { key: 'trait', label: '特质', placeholder: '性格特点、习惯...' },
  { key: 'wound', label: '伤口 / 疤痕', placeholder: '身上的伤疤或印记...' },
  { key: 'phobia', label: '恐惧症', placeholder: '你害怕什么...' },
];

export default function BackgroundEditor({ onComplete }: Props) {
  const [data, setData] = useState<BackgroundData>({
    description: '', belief: '', importantPerson: '',
    valuableThing: '', trait: '', wound: '', phobia: '',
  });

  const update = (key: keyof BackgroundData, val: string) => {
    setData((prev) => ({ ...prev, [key]: val }));
  };

  return (
    <section className="bh-panel">
      <span className="bh-eyebrow">BACKGROUND</span>
      <h2 className="bh-panel-title">背景故事</h2>
      <p style={{ color: 'var(--bh-muted)', fontWeight: 800, fontSize: 13, marginTop: 0 }}>
        填写角色的背景信息，帮助你更好地扮演角色。除个人描述外均可选填。
      </p>

      <div className="bh-form" style={{ width: '100%' }}>
        {FIELDS.map((f) => (
          <div key={f.key} className="bh-field">
            <label>{f.label}</label>
            <textarea
              className="bh-textarea"
              value={data[f.key]}
              onChange={(e) => update(f.key, e.target.value)}
              placeholder={f.placeholder}
              rows={2}
            />
          </div>
        ))}
      </div>

      <button
        className="bh-button bh-button--yellow"
        style={{ width: '100%', marginTop: 16 }}
        onClick={() => onComplete(data)}
      >
        确认背景，进入预览
      </button>
    </section>
  );
}
