import { useState } from 'react';

import type {
  CollaborationContractDTO,
  CollaborationParticipantDTO,
} from '../shared/player-api';


export default function CollaborationContractPanel({
  currentCharacterId,
  participants,
  contracts,
  disabled,
  onCreate,
  onRespond,
  onCancel,
}: {
  currentCharacterId: string;
  participants: CollaborationParticipantDTO[];
  contracts: CollaborationContractDTO[];
  disabled: boolean;
  onCreate: (sharedIntent: string, inviteeCharacterIds: string[]) => void;
  onRespond: (contractId: string, decision: 'accept' | 'decline') => void;
  onCancel: (contractId: string) => void;
}) {
  const [sharedIntent, setSharedIntent] = useState('');
  const [invitees, setInvitees] = useState<string[]>([]);
  const availableInvitees = participants.filter((participant) => participant.characterId !== currentCharacterId);
  const activeContracts = contracts.filter((contract) => ['pending', 'accepted'].includes(contract.status));

  const toggleInvitee = (characterId: string) => {
    setInvitees((current) => {
      if (current.includes(characterId)) return current.filter((item) => item !== characterId);
      return current.length < 3 ? [...current, characterId] : current;
    });
  };

  const submit = () => {
    const intent = sharedIntent.trim();
    if (!intent || invitees.length === 0 || disabled) return;
    onCreate(intent, invitees);
    setSharedIntent('');
    setInvitees([]);
  };

  return (
    <section className="bh-panel" aria-label="协同行动">
      <span className="bh-eyebrow">COLLABORATION</span>
      <h3 className="bh-panel-title">协同行动</h3>
      <p className="bh-hint">邀请只建立共同意图；全员接受并确认关联行动后，系统会作为一个协同批次进入裁决。</p>
      {activeContracts.map((contract) => {
        const isInitiator = contract.initiatorCharacterId === currentCharacterId;
        const awaitingMe = contract.status === 'pending'
          && contract.pendingCharacterIds.includes(currentCharacterId);
        return (
          <article key={contract.contractId} className="bh-muted-box" style={{ marginTop: 10 }}>
            <strong>{awaitingMe ? '协同行动邀请' : '协同行动进度'}</strong>
            <p>{contract.sharedIntent}</p>
            {contract.status === 'accepted' ? <p className="bh-hint">全员已接受；关联行动预览已生成，分别确认后才会进入裁决。</p> : null}
            {awaitingMe ? (
              <div className="bh-action-row bh-action-row--responsive">
                <button className="bh-button bh-button--yellow" type="button" disabled={disabled} onClick={() => onRespond(contract.contractId, 'accept')}>接受</button>
                <button className="bh-button" type="button" disabled={disabled} onClick={() => onRespond(contract.contractId, 'decline')}>拒绝</button>
              </div>
            ) : isInitiator && contract.status === 'pending' ? (
              <div className="bh-action-row bh-action-row--responsive">
                <span className="bh-hint">等待 {contract.pendingCharacterIds.length} 名队友回应。</span>
                <button className="bh-button" type="button" disabled={disabled} onClick={() => onCancel(contract.contractId)}>取消邀请</button>
              </div>
            ) : null}
          </article>
        );
      })}
      <details style={{ marginTop: 12 }}>
        <summary>邀请队友</summary>
        <label className="bh-label" htmlFor="collaboration-intent">共同意图</label>
        <textarea
          id="collaboration-intent"
          value={sharedIntent}
          disabled={disabled}
          maxLength={1000}
          onChange={(event) => setSharedIntent(event.target.value)}
          placeholder="例如：我撬锁，请你警戒走廊。"
        />
        <div className="bh-hint-list" aria-label="选择队友">
          {availableInvitees.map((participant) => (
            <label key={participant.characterId}>
              <input
                type="checkbox"
                checked={invitees.includes(participant.characterId)}
                disabled={disabled || (!invitees.includes(participant.characterId) && invitees.length >= 3)}
                onChange={() => toggleInvitee(participant.characterId)}
              />
              {participant.playerName || participant.characterId}
            </label>
          ))}
        </div>
        <button className="bh-button bh-button--yellow" type="button" disabled={disabled || !sharedIntent.trim() || invitees.length === 0} onClick={submit}>发送邀请</button>
      </details>
    </section>
  );
}
