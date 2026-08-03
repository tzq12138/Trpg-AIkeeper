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
  onInputChange: (value: string) => void;
  onInputModeChange?: (mode: PlayerInputMode) => void;
  onAnalyze: () => void;
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
  const formalActionBusy = phase === 'analyzing' || Boolean(draft) || Boolean(
    receipt && !['armed', 'completed', 'resolved', 'rejected', 'canceled', 'timeout'].includes(receipt.status),
  );
  const statefulInput = isStatefulPlayerInputMode(inputMode, speechRoutesToDialogue);
  const runtimePaused = Boolean(runtimeIntegrity && runtimeIntegrity.status !== 'healthy');
  const editingDisabled = (
    formalActionBusy && !canSendWhileStatefulActionBusy(inputMode, speechRoutesToDialogue)
  ) || ((safetyPaused || runtimePaused) && statefulInput);

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
            onClick={onAnalyze}
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
