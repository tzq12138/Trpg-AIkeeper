import { useState } from 'react';
import { buildHostHeaders } from '../shared/host-auth';
import { getSlotValue } from '../shared/identity';


export default function HostCampaignControls({ roomId }: { roomId: string }) {
  const [scheduledFor, setScheduledFor] = useState('');
  const [objective, setObjective] = useState('');
  const [status, setStatus] = useState('');

  const headers = () => buildHostHeaders(
    getSlotValue('owner_token') || '',
    getSlotValue('account_token') || '',
    true,
  );

  const scheduleSession = async () => {
    if (!scheduledFor) return;
    try {
      const response = await fetch(`/api/host/${encodeURIComponent(roomId)}/campaign-sessions/schedule`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ scheduled_for: new Date(scheduledFor).toISOString() }),
      });
      if (!response.ok) throw new Error('schedule_failed');
      setStatus('下一场时间已发布。');
    } catch {
      setStatus('下一场时间未能保存。');
    }
  };

  const createTeamObjective = async () => {
    if (!objective.trim()) return;
    try {
      const response = await fetch(`/api/host/${encodeURIComponent(roomId)}/objectives`, {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify({ text: objective.trim() }),
      });
      if (!response.ok) throw new Error('objective_failed');
      setObjective('');
      setStatus('队伍目标已更新。');
    } catch {
      setStatus('队伍目标未能保存。');
    }
  };

  return (
    <section className="bh-panel" style={{ marginTop: 16 }}>
      <span className="bh-eyebrow">CAMPAIGN</span>
      <h2 className="bh-panel-title">下一场安排</h2>
      <input className="bh-input" type="datetime-local" value={scheduledFor} onChange={(event) => setScheduledFor(event.target.value)} />
      <button className="bh-button bh-button--yellow" type="button" onClick={() => void scheduleSession}>设置下一场</button>
      <h3 style={{ marginTop: 16 }}>队伍目标</h3>
      <input className="bh-input" value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="例如：查清宅邸地下室的秘密" />
      <button className="bh-button" type="button" onClick={() => void createTeamObjective}>发布队伍目标</button>
      {status && <p className="bh-start-reason">{status}</p>}
    </section>
  );
}
