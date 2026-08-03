import { useEffect, useState } from 'react';

import type {
  ActionConsentDTO,
  ActionConsentOutcomeDTO,
  ActionDraftDTO,
  ActionReceiptDTO,
  ActionStatus,
  RuntimeIntegrityDTO,
} from '../shared/types';
import type { CollaborationParticipantDTO } from '../shared/player-api';
import {
  inputModeSubmitLabel,
  canSendWhileStatefulActionBusy,
  explicitIntentTypeForInputMode,
  isStatefulPlayerInputMode,
  PLAYER_ACTION_COMPOSER_INPUT_MODES,
  PLAYER_INPUT_MODE_LABELS,
  type PlayerInputMode,
} from '../shared/player-input-modes';
import PlayerDecisionCard, { actionStatusLabel } from './PlayerDecisionCard';

export { actionStatusLabel } from './PlayerDecisionCard';


interface PlayerActionComposerProps {
  inputText: string;
  inputMode?: PlayerInputMode;
  phase: ActionStatus;
  draft?: ActionDraftDTO | null;
  ephemeralPreview?: ActionDraftDTO | null;
  receipt?: ActionReceiptDTO | null;
  error?: string;
  safetyPaused?: boolean;
  runtimeIntegrity?: RuntimeIntegrityDTO | null;
  pendingConsent?: ActionConsentDTO | null;
  consentOutcome?: ActionConsentOutcomeDTO | null;
  speechRoutesToDialogue?: boolean;
  collaborationParticipants?: CollaborationParticipantDTO[];
  currentCharacterId?: string;
  availableSkills?: Record<string, number>;
  onInputChange: (value: string) => void;
  onInputModeChange?: (mode: PlayerInputMode) => void;
  onAnalyze: (intentType?: string, params?: Record<string, unknown>) => void;
  onConfirm: (selectedSkill?: string, compositeStepOrder?: string[]) => void;
  onDiscard: () => void;
  onApplyClarification?: (candidate: NonNullable<ActionDraftDTO['candidate_interpretations']>[number]) => void;
  onCancelAction: () => void;
  onResolveCompositeChoice?: (proceed: boolean) => void;
  onRespondConsent?: (consentId: string, accepted: boolean) => void;
  onSubmitFollowUp?: (decision: 'spend_luck' | 'push' | 'decline') => void;
  onUpdateCollaborationDependencies?: (characterIds: string[]) => void;
}


export default function PlayerActionComposer({
  inputText,
  inputMode = 'action',
  phase,
  draft,
  ephemeralPreview,
  receipt,
  error,
  safetyPaused = false,
  runtimeIntegrity = null,
  pendingConsent = null,
  consentOutcome = null,
  speechRoutesToDialogue = false,
  collaborationParticipants = [],
  currentCharacterId,
  availableSkills = {},
  onInputChange,
  onInputModeChange = () => {},
  onAnalyze,
  onConfirm,
  onDiscard,
  onApplyClarification = () => {},
  onCancelAction,
  onResolveCompositeChoice = () => {},
  onRespondConsent = () => {},
  onSubmitFollowUp = () => {},
  onUpdateCollaborationDependencies = () => {},
}: PlayerActionComposerProps) {
  const [affectedPlayerTargetId, setAffectedPlayerTargetId] = useState('');
  const [affectedPlayerEffect, setAffectedPlayerEffect] = useState('restrict_action');
  const [selectedSkillName, setSelectedSkillName] = useState('');
  const formalActionBusy = phase === 'analyzing' || Boolean(draft) || Boolean(
    receipt && !['armed', 'completed', 'resolved', 'rejected', 'canceled', 'timeout'].includes(receipt.status),
  );
  const statefulInput = isStatefulPlayerInputMode(inputMode, speechRoutesToDialogue);
  const runtimePaused = Boolean(runtimeIntegrity && runtimeIntegrity.status !== 'healthy');
  const editingDisabled = (
    formalActionBusy && !canSendWhileStatefulActionBusy(inputMode, speechRoutesToDialogue)
  ) || ((safetyPaused || runtimePaused) && statefulInput);
  const affectedPlayerTargets = collaborationParticipants.filter(
    (participant) => participant.characterId !== currentCharacterId,
  );
  const availableSkillEntries = Object.entries(availableSkills)
    .filter(([name, value]) => name.trim() && Number.isFinite(value))
    .sort(([left], [right]) => left.localeCompare(right, 'zh-CN'));

  useEffect(() => {
    if (
      inputMode !== 'combat_action'
      || ['completed', 'resolved', 'rejected', 'canceled', 'timeout'].includes(phase)
    ) {
      setAffectedPlayerTargetId('');
      setAffectedPlayerEffect('restrict_action');
    }
  }, [inputMode, phase]);

  useEffect(() => {
    if (
      inputMode !== 'action'
      || ['completed', 'resolved', 'rejected', 'canceled', 'timeout'].includes(phase)
    ) {
      setSelectedSkillName('');
    }
  }, [inputMode, phase]);

  const analyze = () => {
    if (inputMode === 'combat_action' && affectedPlayerTargetId) {
      onAnalyze('combat_action', {
        targetId: affectedPlayerTargetId,
        pvpEffect: affectedPlayerEffect,
      });
      return;
    }
    if (inputMode === 'action' && selectedSkillName) {
      onAnalyze('skill_check', { skillName: selectedSkillName });
      return;
    }
    const explicitIntentType = explicitIntentTypeForInputMode(inputMode);
    if (explicitIntentType) {
      onAnalyze(explicitIntentType);
      return;
    }
    onAnalyze();
  };

  return (
    <section className="bh-action-composer" aria-label="玩家行动编辑器">
      <div className="bh-action-box">
        <label className="bh-field-label" htmlFor="player-input-mode">输入类型</label>
        <select
          className="bh-input"
          id="player-input-mode"
          value={inputMode}
          onChange={(event) => onInputModeChange(event.target.value as PlayerInputMode)}
        >
          {PLAYER_ACTION_COMPOSER_INPUT_MODES.map((mode) => (
            <option key={mode} value={mode}>{PLAYER_INPUT_MODE_LABELS[mode]}</option>
          ))}
        </select>
        {inputMode === 'action' && availableSkillEntries.length > 0 && (
          <div className="bh-muted-box" aria-label="技能检定">
            <label className="bh-field-label" htmlFor="player-action-skill">技能检定（可选）</label>
            <select
              className="bh-input"
              id="player-action-skill"
              value={selectedSkillName}
              disabled={editingDisabled}
              onChange={(event) => setSelectedSkillName(event.target.value)}
            >
              <option value="">不指定技能</option>
              {availableSkillEntries.map(([name, value]) => (
                <option key={name} value={name}>{name}（{value}%）</option>
              ))}
            </select>
            <p className="bh-hint">选择后将通过行动预览和权威回执执行检定。</p>
          </div>
        )}
        {inputMode === 'combat_action' && affectedPlayerTargets.length > 0 && (
          <div className="bh-muted-box" aria-label="受影响玩家确认">
            <label className="bh-field-label" htmlFor="affected-player-target">受影响玩家（可选）</label>
            <select
              className="bh-input"
              id="affected-player-target"
              value={affectedPlayerTargetId}
              disabled={editingDisabled}
              onChange={(event) => setAffectedPlayerTargetId(event.target.value)}
            >
              <option value="">只针对场景或 NPC</option>
              {affectedPlayerTargets.map((participant) => (
                <option key={participant.characterId} value={participant.characterId}>
                  {participant.playerName || participant.characterId}
                </option>
              ))}
            </select>
            <label className="bh-field-label" htmlFor="affected-player-effect">机械影响</label>
            <select
              className="bh-input"
              id="affected-player-effect"
              value={affectedPlayerEffect}
              disabled={editingDisabled || !affectedPlayerTargetId}
              onChange={(event) => setAffectedPlayerEffect(event.target.value)}
            >
              <option value="restrict_action">限制行动（需对方确认）</option>
              <option value="damage">造成伤害（需对方确认）</option>
              <option value="resource_take">取得资源（需对方确认）</option>
              <option value="status_change">改变状态（需对方确认）</option>
            </select>
            <p className="bh-hint">选择玩家目标后，只有对方明确接受才会产生机械效果。</p>
          </div>
        )}
        <textarea
          className="bh-textarea"
          value={inputText}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder={inputMode === 'private_note' ? '记录只有你能看到的笔记...' : '描述你现在想说或想做的事...'}
          disabled={editingDisabled}
        />
        <div className="bh-action-row bh-action-row--responsive">
          <button
            className="bh-button bh-button--yellow"
            type="button"
            onClick={analyze}
            disabled={!inputText.trim() || editingDisabled}
          >
            {phase === 'analyzing' && isStatefulPlayerInputMode(inputMode, speechRoutesToDialogue)
              ? '分析中...'
              : inputModeSubmitLabel(inputMode, speechRoutesToDialogue)}
          </button>
          <span className="bh-action-phase" aria-live="polite">{actionStatusLabel(phase)}</span>
        </div>
      </div>

      {error && <p className="bh-error">{error}</p>}

      <PlayerDecisionCard
        draft={draft || ephemeralPreview}
        receipt={receipt}
        pendingConsent={pendingConsent}
        consentOutcome={consentOutcome}
        runtimeIntegrity={runtimeIntegrity}
        inputMode={inputMode}
        speechRoutesToDialogue={speechRoutesToDialogue}
        collaborationParticipants={collaborationParticipants}
        currentCharacterId={currentCharacterId}
        onConfirmDraft={onConfirm}
        onDiscardDraft={onDiscard}
        onApplyClarification={onApplyClarification}
        onCancelAction={onCancelAction}
        onResolveCompositeChoice={onResolveCompositeChoice}
        onRespondConsent={onRespondConsent}
        onSubmitFollowUp={onSubmitFollowUp}
        onUpdateCollaborationDependencies={onUpdateCollaborationDependencies}
      />
    </section>
  );
}
