import { useEffect, useMemo, useState } from 'react';
import CharacterBuilderPage from './CharacterBuilderPage';
import type { BuilderCharacterData } from '../types';
import { getSlotValue, setSlotValue } from '../shared/identity';

interface CharacterPreview {
  name: string;
  occupation: string;
  hp: number;
  max_hp: number;
  san: number;
  max_san: number;
  mp: number;
  max_mp: number;
  luck: number;
  skill_count: number;
  top_skills: Array<{ name: string; value: number }>;
}

interface CharacterPreset extends CharacterPreview {
  preset_id: string;
  file_name: string;
  occupied: boolean;
}

interface ScenarioTemplate {
  template_id: string;
  name: string;
  occupation: string;
  background: string;
  age: number;
  gender: string;
  attributes: Record<string, number>;
  skills: Record<string, number>;
}

type SourceMode = 'preset' | 'upload' | 'builder';
type SelectedSource =
  | { mode: 'preset'; presetId: string }
  | { mode: 'upload'; file: File }
  | { mode: 'builder'; data: BuilderCharacterData }
  | { mode: 'template'; templateId: string };

export default function PlayerJoinPage() {
  const [roomCode, setRoomCode] = useState('');
  const [playerName, setPlayerName] = useState('');
  const [sourceMode, setSourceMode] = useState<SourceMode>('preset');
  const [presets, setPresets] = useState<CharacterPreset[]>([]);
  const [selectedSource, setSelectedSource] = useState<SelectedSource | null>(null);
  const [preview, setPreview] = useState<CharacterPreview | null>(null);
  const [loadingPresets, setLoadingPresets] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState('');
  const [builderDone, setBuilderDone] = useState(false);
  const [scenarioTemplates, setScenarioTemplates] = useState<ScenarioTemplate[]>([]);

  // Check for incoming builder data (from standalone /player/builder page)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get('source') === 'builder') {
      setSourceMode('builder');
      const stored = sessionStorage.getItem('builder_character');
      if (stored) {
        try {
          const data = JSON.parse(stored) as BuilderCharacterData;
          handleBuilderComplete(data);
          sessionStorage.removeItem('builder_character');
          // Clean URL
          window.history.replaceState({}, '', '/player/join');
        } catch { /* ignore */ }
      }
    }
  }, []);

  const normalizedRoomCode = roomCode.trim();
  const normalizedPlayerName = playerName.trim();
  const canConfirm = normalizedRoomCode && normalizedPlayerName && preview && selectedSource && !joining;

  // Fetch scenario templates when room code changes
  useEffect(() => {
    if (!normalizedRoomCode) {
      setScenarioTemplates([]);
      return;
    }
    let cancelled = false;
    fetch(`/api/rooms/${encodeURIComponent(normalizedRoomCode)}`)
      .then((res) => (res.ok ? res.json() : null))
      .then((room: { scenario_id?: string } | null) => {
        if (cancelled || !room?.scenario_id) return;
        return fetch(`/api/scenarios/${room.scenario_id}/templates`);
      })
      .then((res) => (res && res.ok ? res.json() : []))
      .then((templates: ScenarioTemplate[]) => {
        if (!cancelled) setScenarioTemplates(templates);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [normalizedRoomCode]);

  useEffect(() => {
    if (!normalizedRoomCode) {
      setPresets([]);
      return;
    }
    let cancelled = false;
    setLoadingPresets(true);
    fetch(`/api/player/character/presets?room_id=${encodeURIComponent(normalizedRoomCode)}`)
      .then((res) => res.ok ? res.json() : { presets: [] })
      .then((data: { presets?: CharacterPreset[] }) => {
        if (!cancelled) setPresets(data.presets || []);
      })
      .catch(() => {
        if (!cancelled) setPresets([]);
      })
      .finally(() => {
        if (!cancelled) setLoadingPresets(false);
      });
    return () => {
      cancelled = true;
    };
  }, [normalizedRoomCode]);

  const selectedPreset = useMemo(() => {
    if (selectedSource?.mode !== 'preset') return null;
    return presets.find((preset) => preset.preset_id === selectedSource.presetId) || null;
  }, [presets, selectedSource]);

  const choosePreset = (preset: CharacterPreset) => {
    if (preset.occupied) return;
    setError('');
    setSourceMode('preset');
    setSelectedSource({ mode: 'preset', presetId: preset.preset_id });
    setPreview(preset);
  };

  const previewUpload = async (file: File | null) => {
    setError('');
    setPreview(null);
    setSelectedSource(null);
    if (!file) return;
    setSourceMode('upload');
    setPreviewing(true);
    const form = new FormData();
    form.append('file', file);
    try {
      const res = await fetch('/api/player/character/preview-xlsx', {
        method: 'POST',
        body: form,
      });
      if (!res.ok) {
        setError('车卡解析失败，请确认是当前 COC 七版样例卡格式。');
        return;
      }
      const data = await res.json() as CharacterPreview;
      setSelectedSource({ mode: 'upload', file });
      setPreview(data);
    } catch {
      setError('车卡上传失败，请稍后重试。');
    } finally {
      setPreviewing(false);
    }
  };

  /** Called when the inline character builder completes. */
  const handleBuilderComplete = (data: BuilderCharacterData) => {
    const builderPreview: CharacterPreview = {
      name: data.name,
      occupation: data.occupation,
      hp: data.derived_stats.hp,
      max_hp: data.derived_stats.hp,
      san: data.derived_stats.san,
      max_san: data.derived_stats.san,
      mp: data.derived_stats.mp,
      max_mp: data.derived_stats.mp,
      luck: data.attributes.luck,
      skill_count: Object.keys(data.skills).length,
      top_skills: Object.entries(data.skills)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8)
        .map(([name, value]) => ({ name, value })),
    };
    setSelectedSource({ mode: 'builder', data });
    setPreview(builderPreview);
    // Auto-fill player name from character name if empty
    if (!playerName.trim() && data.name) {
      setPlayerName(data.name);
    }
    setBuilderDone(true);
  };

  const join = async () => {
    if (!canConfirm) return;
    // Require login
    const acct = getSlotValue('account_token');
    if (!acct) {
      sessionStorage.setItem('login_return_to', '/player/join');
      window.location.href = '/login';
      return;
    }
    setError('');
    setJoining(true);

    try {
      const authHeaders: Record<string, string> = {};
      const at = getSlotValue('account_token');
      if (at) authHeaders['Authorization'] = `Bearer ${at}`;

      if (selectedSource.mode === 'template') {
        const form = new FormData();
        form.append('player_name', normalizedPlayerName);
        form.append('template_id', selectedSource.templateId);
        const res = await fetch(
          `/api/player/rooms/${encodeURIComponent(normalizedRoomCode)}/join-with-character`,
          { method: 'POST', body: form, headers: authHeaders },
        );
        if (!res.ok) { const d = await res.json().catch(() => ({})); setError(String(d.detail || '加入失败')); return; }
        const data = await res.json();
        setSlotValue('player_token', data.player_token);
        window.location.href = `/player/${normalizedRoomCode}/lobby`;
        return;
      }

      if (selectedSource.mode === 'builder') {
        const form = new FormData();
        form.append('player_name', normalizedPlayerName);
        form.append('character_data', JSON.stringify(selectedSource.data));
        const res = await fetch(
          `/api/player/rooms/${encodeURIComponent(normalizedRoomCode)}/join-with-character`,
          { method: 'POST', body: form, headers: authHeaders },
        );
        if (!res.ok) {
          const detail = await res.json().catch(() => ({}));
          setError(String(detail.detail || '加入失败，请检查昵称和房间码。'));
          return;
        }
        const data = await res.json();
        setSlotValue('player_token', data.player_token);
        window.location.href = `/player/${normalizedRoomCode}/lobby`;
        return;
      }

      // Preset/upload mode: send as before
      const form = new FormData();
      form.append('player_name', normalizedPlayerName);
      if (selectedSource.mode === 'preset') {
        form.append('preset_id', selectedSource.presetId);
      } else {
        form.append('file', selectedSource.file);
      }
      const res = await fetch(
        `/api/player/rooms/${encodeURIComponent(normalizedRoomCode)}/join-with-character`,
        { method: 'POST', body: form, headers: authHeaders },
      );
      if (!res.ok) {
        if (res.status === 404) setError('房间不存在，检查一下房间码。');
        else if (res.status === 409) setError('这张预设车卡刚刚被选走了，请换一张。');
        else setError('加入失败，请检查昵称和车卡。');
        if (selectedSource.mode === 'preset') {
          refreshPresets();
        }
        return;
      }
      const data = await res.json();
      setSlotValue('player_token', data.player_token);
      window.location.href = `/player/${normalizedRoomCode}/lobby`;
    } catch {
      setError('加入失败，当前服务可能没有启动。');
    } finally {
      setJoining(false);
    }
  };

  const refreshPresets = () => {
    if (!normalizedRoomCode) return;
    setLoadingPresets(true);
    fetch(`/api/player/character/presets?room_id=${encodeURIComponent(normalizedRoomCode)}`)
      .then((res) => res.ok ? res.json() : { presets: [] })
      .then((data: { presets?: CharacterPreset[] }) => setPresets(data.presets || []))
      .catch(() => setPresets([]))
      .finally(() => setLoadingPresets(false));
  };

  const accountToken = getSlotValue('account_token');
  const account = accountToken ? JSON.parse(getSlotValue('account') || '{}') : null;

  return (
    <section className="bh-panel bh-join">
      {/* Account bar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16, padding: '8px 12px', border: '3px solid var(--bh-black)', background: 'var(--bh-paper-2)' }}>
        <span style={{ fontWeight: 900, fontSize: 13 }}>{account ? `👤 ${account.display_name || account.username}` : '👻 游客模式'}</span>
        <span style={{ flex: 1 }} />
        {account ? (
          <button className="bh-button" style={{ minHeight: 30, fontSize: 11, padding: '4px 10px' }} onClick={() => { setSlotValue('account_token', ''); setSlotValue('account', ''); window.location.reload(); }}>登出</button>
        ) : (
          <a className="bh-button bh-button--yellow" style={{ minHeight: 30, fontSize: 11, padding: '4px 10px' }} href="/login" onClick={(e) => { e.preventDefault(); sessionStorage.setItem('login_return_to', '/player/join'); window.location.href = '/login'; }}>登录</a>
        )}
      </div>

      <span className="bh-eyebrow">INVESTIGATOR ACCESS</span>
      <h2 className="bh-panel-title">加入房间</h2>

      <div className="bh-join-layout">
        <div className="bh-form">
          <label className="bh-field">
            <span>房间码</span>
            <input
              className="bh-input"
              placeholder="例如：a1b2c3d4"
              value={roomCode}
              onChange={(event) => setRoomCode(event.target.value)}
            />
          </label>
          <label className="bh-field">
            <span>玩家昵称</span>
            <input
              className="bh-input"
              placeholder="Host 看到的名字"
              value={playerName}
              onChange={(event) => setPlayerName(event.target.value)}
            />
          </label>

          <div className="bh-source-toggle" role="tablist" aria-label="车卡来源" style={{ gridTemplateColumns: '1fr 1fr 1fr' }}>
            <button
              className={`bh-button ${sourceMode === 'preset' ? 'bh-button--yellow' : ''}`}
              type="button"
              onClick={() => {
                setSourceMode('preset');
                setSelectedSource(selectedPreset ? { mode: 'preset', presetId: selectedPreset.preset_id } : null);
                setPreview(selectedPreset);
              }}
            >
              选择预设
            </button>
            <button
              className={`bh-button ${sourceMode === 'upload' ? 'bh-button--yellow' : ''}`}
              type="button"
              onClick={() => setSourceMode('upload')}
            >
              上传车卡
            </button>
            <button
              className={`bh-button ${sourceMode === 'builder' ? 'bh-button--yellow' : ''}`}
              type="button"
              onClick={() => { setSourceMode('builder'); setBuilderDone(false); }}
            >
              现场车卡
            </button>
          </div>

          {sourceMode === 'upload' && (
            <label className="bh-upload-box">
              <span>{previewing ? '解析中...' : '上传 xlsx 车卡'}</span>
              <input
                type="file"
                accept=".xlsx"
                onChange={(event) => previewUpload(event.target.files?.[0] || null)}
                disabled={previewing}
              />
            </label>
          )}

          {error && <p className="bh-error">{error}</p>}
        </div>

        <div>
          {sourceMode === 'preset' && (
            <PresetList
              loading={loadingPresets}
              presets={presets}
              templates={scenarioTemplates}
              selectedId={selectedSource?.mode === 'preset' ? selectedSource.presetId : ''}
              onChoose={choosePreset}
              onChooseTemplate={(tpl, pv) => {
                setSelectedSource({ mode: 'template', templateId: tpl.template_id });
                setPreview(pv);
              }}
            />
          )}

          {sourceMode === 'builder' && !builderDone && (
            <CharacterBuilderPage
              onComplete={handleBuilderComplete}
              onCancel={() => {
                setSourceMode('preset');
                setSelectedSource(null);
                setPreview(null);
                setBuilderDone(false);
              }}
            />
          )}

          {sourceMode === 'builder' && builderDone && preview && (
            <div style={{ marginBottom: 16 }}>
              <div className="bh-preview-box" style={{ padding: 14 }}>
                <span className="bh-eyebrow">BUILDER COMPLETE</span>
                <strong style={{ fontFamily: '"Space Grotesk", Impact, sans-serif', fontSize: 18 }}>
                  {preview.name} — {preview.occupation}
                </strong>
                <p style={{ margin: '4px 0 0', color: 'var(--bh-muted)', fontWeight: 700, fontSize: 13 }}>
                  角色已创建，请在下方确认加入房间。
                </p>
              </div>
            </div>
          )}

          <CharacterPreviewPanel preview={preview} playerName={normalizedPlayerName} sourceMode={sourceMode} />
          <button
            className="bh-button bh-button--yellow bh-confirm-button"
            type="button"
            onClick={join}
            disabled={!canConfirm}
          >
            {joining ? '加入中...' : '确认并进入'}
          </button>
        </div>
      </div>
    </section>
  );
}

function PresetList({ loading, presets, templates, selectedId, onChoose, onChooseTemplate }: {
  loading: boolean;
  presets: CharacterPreset[];
  templates: ScenarioTemplate[];
  selectedId: string;
  onChoose: (preset: CharacterPreset) => void;
  onChooseTemplate?: (tpl: ScenarioTemplate, preview: CharacterPreset) => void;
}) {
  if (loading) {
    return <div className="bh-muted-box">正在读取预设调查员...</div>;
  }
  const hasPresets = presets.length > 0;
  const hasTemplates = templates.length > 0;
  if (!hasPresets && !hasTemplates) {
    return <div className="bh-muted-box">暂无本地预设车卡。你可以上传 xlsx 或现场创建一张车卡。</div>;
  }

  return (
    <div className="bh-preset-list">
      {/* Scenario protagonist templates */}
      {hasTemplates && (
        <>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span className="bh-eyebrow" style={{ fontSize: 9, padding: '3px 6px', margin: 0 }}>SCENARIO</span>
            <span style={{ fontSize: 11, fontWeight: 900, color: 'var(--bh-muted)' }}>剧本推荐角色</span>
          </div>
          {templates.map((tpl) => (
            <button
              key={tpl.template_id}
              className="bh-preset-card"
              type="button"
              onClick={() => {
                const preview: CharacterPreset = {
                  preset_id: `tpl_${tpl.template_id}`,
                  file_name: tpl.name,
                  name: tpl.name,
                  occupation: tpl.occupation,
                  hp: tpl.attributes?.con ? Math.floor((Number(tpl.attributes.con) + Number(tpl.attributes.siz || 60)) / 10) : 10,
                  max_hp: tpl.attributes?.con ? Math.floor((Number(tpl.attributes.con) + Number(tpl.attributes.siz || 60)) / 10) : 10,
                  san: tpl.attributes?.pow || 50,
                  max_san: tpl.attributes?.pow || 50,
                  mp: tpl.attributes?.pow ? Math.floor(Number(tpl.attributes.pow) / 5) : 10,
                  max_mp: tpl.attributes?.pow ? Math.floor(Number(tpl.attributes.pow) / 5) : 10,
                  luck: tpl.attributes?.luck || 50,
                  skill_count: Object.keys(tpl.skills).length,
                  top_skills: Object.entries(tpl.skills).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([name, value]) => ({ name, value })),
                  occupied: false,
                };
                if (onChooseTemplate) {
                  const preset: CharacterPreset = { ...preview, preset_id: `tpl_${tpl.template_id}`, file_name: tpl.name, occupied: false };
                  onChooseTemplate(tpl, preset);
                }
              }}
            >
              <strong>{tpl.name}</strong>
              <span>{tpl.occupation || '剧本角色'}</span>
              <small>{tpl.background ? tpl.background.slice(0, 40) + '...' : '剧本推荐'}</small>
            </button>
          ))}
        </>
      )}

      {/* Server-side presets */}
      {hasPresets && hasTemplates && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, marginBottom: 4 }}>
          <span className="bh-eyebrow" style={{ fontSize: 9, padding: '3px 6px', margin: 0 }}>PRESETS</span>
          <span style={{ fontSize: 11, fontWeight: 900, color: 'var(--bh-muted)' }}>通用预设</span>
        </div>
      )}
      {hasPresets && presets.map((preset) => (
        <button
          className={`bh-preset-card ${selectedId === preset.preset_id ? 'bh-preset-card--selected' : ''}`}
          key={preset.preset_id}
          type="button"
          onClick={() => onChoose(preset)}
          disabled={preset.occupied}
        >
          <strong>{preset.name || preset.file_name}</strong>
          <span>{preset.occupation || '未知职业'}</span>
          <small>{preset.occupied ? '已被选择' : `技能 ${preset.skill_count}`}</small>
        </button>
      ))}
    </div>
  );
}

function CharacterPreviewPanel({ preview, playerName, sourceMode }: {
  preview: CharacterPreview | null;
  playerName: string;
  sourceMode: SourceMode;
}) {
  if (!preview) {
    const hints: Record<SourceMode, string> = {
      preset: '选择预设或上传车卡后，这里会显示调查员摘要。',
      upload: '上传 xlsx 车卡后，这里会显示解析结果。',
      builder: '完成车卡向导后，这里会显示预览。',
    };
    return (
      <div className="bh-preview-box">
        <span className="bh-eyebrow">PREVIEW</span>
        <p>{hints[sourceMode]}</p>
      </div>
    );
  }
  return (
    <div className="bh-preview-box">
      <span className="bh-eyebrow">CHARACTER READY</span>
      <h3>{playerName ? `${playerName} / ${preview.name}` : preview.name}</h3>
      <p>{preview.occupation || '未知职业'}</p>
      <div className="bh-preview-stats">
        <span>HP {preview.hp}/{preview.max_hp}</span>
        <span>SAN {preview.san}/{preview.max_san}</span>
        <span>MP {preview.mp}/{preview.max_mp}</span>
        <span>LUCK {preview.luck}</span>
      </div>
      <div className="bh-skill-chips">
        {preview.top_skills.length === 0 && <span>暂无技能数据</span>}
        {preview.top_skills.slice(0, 6).map((skill) => (
          <span key={skill.name}>{skill.name} {skill.value}</span>
        ))}
      </div>
    </div>
  );
}
