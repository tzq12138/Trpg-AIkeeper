import { useEffect, useState } from 'react';
import { buildHostHeaders } from '../shared/host-auth';
import { getSlotValue } from '../shared/identity';
import {
  normalizePublicStage,
  normalizePublicStagePresentation,
  type PublicStageData,
  type PublicStagePresentation,
} from './publicStageModel';

function formatTime(value: string) {
  if (!value) return '';
  const time = new Date(value);
  return Number.isNaN(time.valueOf()) ? '' : time.toLocaleTimeString('zh-CN', {
    hour: '2-digit', minute: '2-digit',
  });
}

export default function HostStage({ roomId }: { roomId: string }) {
  const [stage, setStage] = useState<PublicStageData | null>(null);
  const [presentation, setPresentation] = useState<PublicStagePresentation | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch(`/api/host/${encodeURIComponent(roomId)}/stage-projection`, {
          headers: buildHostHeaders(
            getSlotValue('owner_token') || '',
            getSlotValue('account_token') || '',
          ),
        });
        if (!response.ok) throw new Error('stage projection unavailable');
        const payload = await response.json() as Record<string, unknown>;
        if (!cancelled) {
          setStage(normalizePublicStage(payload));
          setError('');
        }
        const presentationResponse = await fetch(`/api/host/${encodeURIComponent(roomId)}/stage-presentation`, {
          headers: buildHostHeaders(
            getSlotValue('owner_token') || '',
            getSlotValue('account_token') || '',
          ),
        });
        if (!presentationResponse.ok) throw new Error('stage presentation unavailable');
        const presentationPayload = await presentationResponse.json() as Record<string, unknown>;
        if (!cancelled) setPresentation(normalizePublicStagePresentation(presentationPayload));
      } catch {
        if (!cancelled) {
          setPresentation(null);
          setError('公共舞台暂时无法同步，将自动重试。');
        }
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [roomId]);

  const recentEvents = stage?.recent_events || [];
  const latestNarration = presentation?.available && presentation.narrative_text
    ? presentation.narrative_text
    : recentEvents[recentEvents.length - 1]?.text || '等待调查员行动。';
  const combatPhaseText = {
    declaration: '声明行动',
    resolution: '正在结算',
    summary: '轮末总结',
    blocked: '等待规则决定',
  } as const;
  const combatDistanceText = {
    engaged: '贴身',
    near: '近距离',
    short: '短距离',
    medium: '中距离',
    long: '远距离',
  } as const;

  return (
    <main className="bh-host bh-public-stage" aria-label="公共舞台">
      <header className="bh-host-topbar">
        <div className="bh-host-brand">
          <strong className="bh-panel-title" style={{ margin: 0 }}>AI-KEEPER</strong>
          <span className="bh-room-code">公共舞台 · 房间 {roomId}</span>
        </div>
        <span className="bh-eyebrow">{stage?.status_text || '等待调查员行动'}</span>
      </header>

      {error && <p className="bh-stage-notice">{error}</p>}
      <div className="bh-host-layout">
        <section className="bh-stage-panel">
          <div className="bh-stage-label">PUBLIC STAGE</div>
          <div className="bh-projection">
            {stage?.scene_image_url && (
              <div className="bh-projection-image" style={{ backgroundImage: `url(${stage.scene_image_url})` }} />
            )}
            <div className="bh-projection-copy">
              <h1>当前场景</h1>
              <p>{latestNarration}</p>
            </div>
          </div>
        </section>

        <aside className="bh-monitor" aria-label="队伍公开状态">
          <section className="bh-muted-box" aria-label="公开局势">
            <strong>公开局势</strong>
            <p>{stage?.scene_time || '时间未定'}</p>
            {stage?.team_objectives.length ? <ul>{stage.team_objectives.map((objective) => <li key={objective}>{objective}</li>)}</ul> : <p>暂无团队目标。</p>}
          </section>
          {stage?.combat_round && (
            <section className="bh-muted-box" aria-label="战斗进度">
              <strong>第 {stage.combat_round.round_number} 轮 · {combatPhaseText[stage.combat_round.phase]}</strong>
              {stage.combat_round.phase === 'declaration' ? (
                <p>已完成声明：{stage.combat_round.submitted_count} / {stage.combat_round.total_players}</p>
              ) : stage.combat_round.current_conflict ? (
                <p>当前冲突：{stage.combat_round.current_conflict}</p>
              ) : <p>本轮局势正在整理。</p>}
              {stage.combat_round.public_units?.length ? (
                <div className="bh-hint-list" aria-label="公开参与单位">
                  <strong>公开参与单位</strong>
                  {stage.combat_round.public_units.map((unit) => (
                    <p key={`${unit.kind}-${unit.label}`}>
                      {unit.label} · {unit.condition}
                      {typeof unit.health_segments === 'number' ? ` ${'█'.repeat(unit.health_segments)}${'░'.repeat(8 - unit.health_segments)}` : ''}
                      {unit.distance_band ? ` · ${combatDistanceText[unit.distance_band]}` : ''}
                      {unit.last_observed_at ? ` · 最后发现：${unit.last_observed_at}` : ''}
                    </p>
                  ))}
                </div>
              ) : null}
            </section>
          )}
          <div className="bh-monitor-label">调查员状态</div>
          <div className="bh-player-monitor-list">
            {stage?.players.length ? stage.players.map((player) => (
              <article className={`bh-player-card bh-player-card--${player.condition_tone}`} key={player.character_id}>
                <h2>{player.investigator_name || player.player_name}</h2>
                <p className="bh-subtitle">{player.condition}</p>
              </article>
            )) : (
              <article className="bh-player-card">
                <h2>等待调查员</h2>
                <p>玩家加入后会在这里显示公开状态。</p>
              </article>
            )}
          </div>
          <section className="bh-muted-box" aria-label="近期公开事件">
            <strong>近期事件</strong>
            {stage?.recent_events.length ? (
              <ol>
                {stage.recent_events.slice(-5).reverse().map((event, index) => (
                  <li key={`${event.issued_at}-${index}`}>
                    {formatTime(event.issued_at)} {event.text}
                  </li>
                ))}
              </ol>
            ) : <p>暂无公开事件。</p>}
          </section>
        </aside>
      </div>
    </main>
  );
}
