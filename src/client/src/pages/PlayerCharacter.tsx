import { useState, useEffect } from 'react';
import { apiFetch, authHeaders } from '../api';
import type { CharacterSheet, SkillCheckResult } from '../types';

export default function PlayerCharacter() {
  const [char, setChar] = useState<CharacterSheet | null>(null);
  const [checkResult, setCheckResult] = useState<SkillCheckResult | null>(null);
  const [rolling, setRolling] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<CharacterSheet>('/api/player/character', { headers: authHeaders() })
      .then(setChar)
      .catch(() => {});
  }, []);

  const rollSkill = async (skillName: string, skillValue: number) => {
    if (rolling) return;
    setRolling(skillName);
    setCheckResult(null);
    try {
      const result = await apiFetch<SkillCheckResult>('/api/player/skill-check', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ skill_name: skillName, skill_value: skillValue }),
      });
      setCheckResult(result);
    } catch {
      // ignore
    } finally {
      setRolling(null);
    }
  };

  if (!char) return <p style={{ color: '#aaa', textAlign: 'center', marginTop: 40 }}>加载中...</p>;

  const stats = [
    { label: 'HP', value: char.hp, max: char.max_hp, color: '#e53935' },
    { label: 'SAN', value: char.san, max: char.max_san, color: '#7c4dff' },
    { label: 'MP', value: char.mp, max: char.max_mp, color: '#2196f3' },
    { label: 'LUCK', value: char.luck, max: null, color: '#ff9800' },
  ];

  const successColor: Record<string, string> = {
    critical: '#ffd700',
    extreme: '#e040fb',
    hard: '#7c4dff',
    regular: '#4caf50',
    failure: '#e53935',
    fumble: '#b71c1c',
  };

  return (
    <div>
      <h2 style={{ marginBottom: 12 }}>{char.name || '未命名调查员'}</h2>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
        {stats.map((s) => (
          <div key={s.label} style={{
            background: 'rgba(255,255,255,0.05)',
            borderRadius: 8,
            padding: '10px 12px',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: 11, color: '#888' }}>{s.label}</div>
            <div style={{ fontSize: 22, fontWeight: 'bold', color: s.color }}>
              {s.value}{s.max != null ? <span style={{ fontSize: 13, color: '#666' }}>/{s.max}</span> : null}
            </div>
          </div>
        ))}
      </div>

      {char.background && (
        <div style={{
          background: 'rgba(255,255,255,0.03)',
          borderRadius: 8,
          padding: 12,
          marginBottom: 16,
          fontSize: 13,
          color: '#aaa',
        }}>
          {char.background}
        </div>
      )}

      <h3 style={{ marginBottom: 8, fontSize: 15 }}>技能</h3>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {Object.entries(char.skills).map(([name, value]) => (
          <button
            key={name}
            onClick={() => rollSkill(name, value)}
            disabled={rolling !== null}
            style={{
              padding: '6px 12px',
              borderRadius: 6,
              border: '1px solid #333',
              background: rolling === name ? '#3f51b5' : 'rgba(255,255,255,0.05)',
              color: '#ddd',
              fontSize: 13,
              cursor: rolling ? 'not-allowed' : 'pointer',
              opacity: rolling && rolling !== name ? 0.5 : 1,
            }}
          >
            {name} ({value})
          </button>
        ))}
      </div>

      {checkResult && (
        <div style={{
          marginTop: 16,
          padding: 14,
          borderRadius: 10,
          background: 'rgba(255,255,255,0.05)',
          border: `2px solid ${successColor[checkResult.success_level] || '#333'}`,
        }}>
          <div style={{ fontSize: 14, fontWeight: 'bold', marginBottom: 4 }}>
            {checkResult.skill_name} 检定
          </div>
          <div style={{ fontSize: 13, color: '#aaa' }}>
            掷骰: <strong style={{ color: '#fff', fontSize: 18 }}>{checkResult.roll}</strong>
            {' '}/ 阈值: {checkResult.skill_value}
          </div>
          <div style={{
            marginTop: 6,
            fontSize: 16,
            fontWeight: 'bold',
            color: successColor[checkResult.success_level] || '#fff',
          }}>
            {checkResult.success_level === 'critical' && '大成功!'}
            {checkResult.success_level === 'extreme' && '极难成功'}
            {checkResult.success_level === 'hard' && '困难成功'}
            {checkResult.success_level === 'regular' && '常规成功'}
            {checkResult.success_level === 'failure' && '失败'}
            {checkResult.success_level === 'fumble' && '大失败!'}
          </div>
        </div>
      )}
    </div>
  );
}
