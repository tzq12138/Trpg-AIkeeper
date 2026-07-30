import type { ActionDraftDTO, ActionReceiptDTO, ActionStatus } from '../shared/types';
import type { CollaborationParticipantDTO } from '../shared/player-api';
import { useEffect, useState } from 'react';
import RedactedCitationDisclosure from './RedactedCitationDisclosure';
import {
  confirmationImpactSummary,
  inputModeSubmitLabel,
  canSendWhileStatefulActionBusy,
  isStatefulPlayerInputMode,
  PLAYER_ACTION_COMPOSER_INPUT_MODES,
  PLAYER_INPUT_MODE_LABELS,
  type PlayerInputMode,
} from '../shared/player-input-modes';


interface PlayerActionComposerProps {
  inputText: string;
  inputMode?: PlayerInputMode;
  phase: ActionStatus;
  draft?: ActionDraftDTO | null;
  ephemeralPreview?: ActionDraftDTO | null;
  receipt?: ActionReceiptDTO | null;
  error?: string;
  safetyPaused?: boolean;
  speechRoutesToDialogue?: boolean;
  collaborationParticipants?: CollaborationParticipantDTO[];
  currentCharacterId?: string;
  onInputChange: (value: string) => void;
  onInputModeChange?: (mode: PlayerInputMode) => void;
  onAnalyze: () => void;
  onConfirm: (selectedSkill?: string, compositeStepOrder?: string[]) => void;
  onDiscard: () => void;
  onCancelAction: () => void;
  onResolveCompositeChoice?: (proceed: boolean) => void;
  onUpdateCollaborationDependencies?: (characterIds: string[]) => void;
}

const RISK_LABELS = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
} as const;

const ACTION_STATUS_LABELS: Record<ActionStatus, string> = {
  idle: '等待输入',
  typing: '正在编辑',
  analyzing: '正在理解行动',
  awaiting_confirmation: '等待确认',
  armed: '已布防，等待公开规则事件',
  queued: '已进入队列',
  batched: '正在合并行动',
  resolving: '正在裁决',
  awaiting_player_choice: '等待你的选择',
  awaiting_host_exception: '等待异常处理',
  completed: '已完成',
  resolved: '已完成',
  rejected: '未能执行',
  canceled: '已撤回',
  timeout: '已超时',
  sync_required: '需要同步状态',
};

export function actionStatusLabel(status: ActionStatus): string {
  return ACTION_STATUS_LABELS[status];
}

function formatRolls(rawRolls: unknown): string {
  if (!Array.isArray(rawRolls)) {
    return '—';
  }
  const rolls = rawRolls
    .filter((roll): roll is Record<string, unknown> => Boolean(roll) && typeof roll === 'object')
    .map((roll) => `${String(roll.dice ?? 'd100')} ${String(roll.result ?? '—')}`);
  return rolls.join(' · ') || '—';
}

function formatState(snapshot: Record<string, unknown>): string {
  const values = Object.entries(snapshot)
    .filter(([, value]) => typeof value !== 'object')
    .map(([key, value]) => `${key.toUpperCase()} ${String(value)}`);
  return values.join(' · ') || '无变化';
}

function collaborationDependencies(draft: ActionDraftDTO | null | undefined): string[] {
  const rawDependencies = draft?.params.dependsOnCharacterIds;
  return Array.isArray(rawDependencies)
    ? rawDependencies.filter((value): value is string => typeof value === 'string')
    : [];
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
  speechRoutesToDialogue = false,
  collaborationParticipants = [],
  currentCharacterId,
  onInputChange,
  onInputModeChange = () => {},
  onAnalyze,
  onConfirm,
  onDiscard,
  onCancelAction,
  onResolveCompositeChoice = () => {},
  onUpdateCollaborationDependencies = () => {},
}: PlayerActionComposerProps) {
  const [selectedSkill, setSelectedSkill] = useState('');
  const [compositeStepOrder, setCompositeStepOrder] = useState<string[]>([]);
  const [dependencyCharacterIds, setDependencyCharacterIds] = useState<string[]>(
    () => collaborationDependencies(draft),
  );
  const preview = draft || ephemeralPreview;
  const skillChoices = preview
    ? [preview.suggested_skill, ...preview.alternative_skills].filter(
      (skill): skill is string => Boolean(skill),
    )
    : [];
  const requiresSkillChoice = Boolean(draft && preview && preview.alternative_skills.length > 0);
  const currentCompositeOrder = preview?.composite_steps.length === 2
    ? compositeStepOrder.length === 2
      ? compositeStepOrder
      : preview.composite_steps.map((step) => step.step_id)
    : [];
  const orderedCompositeSteps = preview?.composite_steps.length === 2
    ? currentCompositeOrder.map((stepId) => preview.composite_steps.find((step) => step.step_id === stepId))
      .filter((step): step is ActionDraftDTO['composite_steps'][number] => Boolean(step))
    : [];
  const clarificationOptions = preview?.candidate_interpretations || [];
  const isCollaborationDraft = typeof draft?.params.collaborationContractId === 'string';
  const collaborationTeammates = collaborationParticipants.filter(
    (participant) => participant.characterId !== currentCharacterId,
  );
  const ruleExplanation = receipt?.rule_explanation;
  const compositeChoice = extractCompositeChoice(receipt?.result);
  const authoritativeInputs = ruleExplanation?.authoritative_inputs ?? {};
  const formalActionBusy = phase === 'analyzing' || Boolean(draft) || Boolean(
    receipt && !['armed', 'completed', 'resolved', 'rejected', 'canceled', 'timeout'].includes(receipt.status),
  );
  const statefulInput = isStatefulPlayerInputMode(
    inputMode,
    speechRoutesToDialogue,
  );
  const editingDisabled = (
    formalActionBusy && !canSendWhileStatefulActionBusy(
      inputMode,
      speechRoutesToDialogue,
    )
  ) || (safetyPaused && statefulInput);

  useEffect(() => {
    setSelectedSkill('');
    setCompositeStepOrder(draft?.composite_steps.map((step) => step.step_id) || []);
    setDependencyCharacterIds(collaborationDependencies(draft));
  }, [draft?.draft_id, draft?.revision]);

  const toggleCollaborationDependency = (characterId: string) => {
    const nextDependencies = dependencyCharacterIds.includes(characterId)
      ? dependencyCharacterIds.filter((value) => value !== characterId)
      : [...dependencyCharacterIds, characterId];
    setDependencyCharacterIds(nextDependencies);
    onUpdateCollaborationDependencies(nextDependencies);
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
          {PLAYER_ACTION_COMPOSER_INPUT_MODES.map((mode) => <option key={mode} value={mode}>{PLAYER_INPUT_MODE_LABELS[mode]}</option>)}
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

      {preview && (
        <article className={`bh-action-preview bh-action-preview--${preview.risk}`}>
          <div className="bh-action-preview__header">
            <span className="bh-eyebrow">
              {preview.ephemeral ? '临时理解（不保存）' : '行动确认'}
            </span>
            <strong>{RISK_LABELS[preview.risk]}</strong>
          </div>
          <p>{preview.understanding_summary}</p>
          {preview.intent_contract && (
            <dl className="bh-action-preview__facts">
              {preview.intent_contract.target && <div><dt>目标</dt><dd>{preview.intent_contract.target}</dd></div>}
              {preview.intent_contract.method && <div><dt>方法</dt><dd>{preview.intent_contract.method}</dd></div>}
              {preview.intent_contract.conditions.length > 0 && <div><dt>条件</dt><dd>{preview.intent_contract.conditions.join('；')}</dd></div>}
              {preview.intent_contract.ambiguities.length > 0 && <div><dt>待澄清</dt><dd>{preview.intent_contract.ambiguities.join('；')}</dd></div>}
            </dl>
          )}
          <dl className="bh-action-preview__facts">
            <div><dt>技能</dt><dd>{preview.suggested_skill || '无需技能'}</dd></div>
            <div><dt>难度</dt><dd>{preview.difficulty || '无'}</dd></div>
            {preview.resource_impacts.length > 0 && (
              <div>
                <dt>资源影响</dt>
                <dd>
                  {preview.resource_impacts.map((impact, index) => (
                    <span key={`${String(impact.resource || impact.label || 'resource')}-${index}`}>
                      {String(impact.label || impact.resource || '资源')}
                      {impact.dice ? ` -${String(impact.dice)}` : ''}
                    </span>
                  ))}
                </dd>
              </div>
            )}
            <div><dt>可见性</dt><dd>{preview.visibility}</dd></div>
            <div><dt>置信度</dt><dd>{Math.round(preview.confidence * 100)}%</dd></div>
          </dl>
          {requiresSkillChoice && (
            <div className="bh-muted-box">
              <label className="bh-field-label" htmlFor="selected-action-skill">选择采用的技能</label>
              <select
                id="selected-action-skill"
                className="bh-input"
                value={selectedSkill}
                onChange={(event) => setSelectedSkill(event.target.value)}
              >
                <option value="">请选择技能</option>
                {skillChoices.map((skill) => <option key={skill} value={skill}>{skill}</option>)}
              </select>
              <p style={{ marginTop: 6, fontSize: 12 }}>系统会以你选定的技能读取服务器角色卡数值，不能自行填写其他技能。</p>
            </div>
          )}
          {orderedCompositeSteps.length === 2 && (
            <div className="bh-muted-box">
              <strong>组合行动（同一回合，仅消耗一次行动）</strong>
              <ol>
                {orderedCompositeSteps.map((step, index) => (
                  <li key={step.step_id}>
                    {step.summary}
                    {index === 1 && <small> · {
                      step.execution_condition === 'previous_step_success'
                        ? '仅在第一步成功时执行'
                        : step.execution_condition === 'previous_step_failure'
                          ? '仅在第一步失败时执行'
                          : '无论第一步结果都会执行'
                    }{step.execution_condition === 'previous_step_success' && `；第一步失败时：${
                      step.on_previous_failure === 'cancel'
                        ? '自动取消此步'
                        : step.on_previous_failure === 'ask'
                          ? '询问你是否继续'
                          : '继续尝试此步'
                    }`}</small>}
                  </li>
                ))}
              </ol>
              <button
                className="bh-button"
                type="button"
                onClick={() => setCompositeStepOrder((current) => [...current].reverse())}
              >
                调整顺序
              </button>
            </div>
          )}
          {isCollaborationDraft && collaborationTeammates.length > 0 && (
            <div className="bh-muted-box">
              <strong>协同行动顺序</strong>
              <p>只勾选你的行动必须等待其完成的队友。若前置行动未能完成，你的行动会进入异常处理，不会自动改写结果。</p>
              {collaborationTeammates.map((participant) => (
                <label key={participant.characterId} className="bh-checkbox-row">
                  <input
                    type="checkbox"
                    checked={dependencyCharacterIds.includes(participant.characterId)}
                    onChange={() => toggleCollaborationDependency(participant.characterId)}
                  />
                  等待 {participant.playerName} 的行动
                </label>
              ))}
            </div>
          )}
          {draft?.status === 'analyzing' && clarificationOptions.length > 0 && (
            <div className="bh-muted-box">
              <strong>请先选择本回合的主要事项</strong>
              <p>系统不会把超过两项的描述自动拆成多次行动；选择后会保留为新描述，等待你重新分析。</p>
              <div className="bh-action-row bh-action-row--responsive">
                {clarificationOptions.map((option, index) => {
                  const label = option.label || `主要事项 ${index + 1}`;
                  const replacementIntent = option.replacement_intent || option.interpreted_intent || label;
                  return (
                    <button
                      className="bh-button"
                      key={`${label}-${index}`}
                      type="button"
                      onClick={() => {
                        onDiscard();
                        onInputChange(replacementIntent);
                      }}
                    >
                      {label}：保留并重新分析
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          {preview.confirmation_requirements.length > 0 && (
            <div className="bh-confirmation-list">
              {preview.confirmation_requirements.map((requirement) => (
                <code key={requirement}>{requirement}</code>
              ))}
            </div>
          )}
          {draft?.requires_confirmation && (
            <p className="bh-muted-box">
              <strong>确认后：</strong>{confirmationImpactSummary(inputMode, speechRoutesToDialogue)}
            </p>
          )}
          <RedactedCitationDisclosure citations={preview.citations || []} />
          {draft && (
            <div className="bh-action-row bh-action-row--responsive">
              {draft.status === 'awaiting_confirmation' && (
                <button
                  className="bh-button bh-button--yellow"
                  type="button"
                  disabled={requiresSkillChoice && !selectedSkill}
                  onClick={() => onConfirm(
                    selectedSkill || undefined,
                    orderedCompositeSteps.length === 2
                      ? orderedCompositeSteps.map((step) => step.step_id)
                      : undefined,
                  )}
                >
                  确认并提交
                </button>
              )}
              <button className="bh-button" type="button" onClick={onDiscard}>
                {draft.status === 'analyzing' && preview.intent_contract?.ambiguities.length
                  ? '修改描述'
                  : '放弃草稿'}
              </button>
            </div>
          )}
        </article>
      )}

      {receipt && (
        <article className="bh-action-receipt" aria-live="polite">
          <div className="bh-action-preview__header">
            <span className="bh-eyebrow">ACTION RECEIPT</span>
            <strong>{actionStatusLabel(receipt.status)}</strong>
          </div>
          <ol className="bh-action-timeline">
            {receipt.timeline.map((event, index) => (
              <li key={`${event.status}-${event.created_at}-${index}`}>
                <strong>{actionStatusLabel(event.status)}</strong>
                <time>{event.created_at}</time>
              </li>
            ))}
          </ol>
          {(receipt.transaction_id || receipt.state_version !== null) && (
            <p className="bh-muted">
              {receipt.transaction_id ? `事务：${receipt.transaction_id}` : '事务：处理中'}
              {receipt.state_version !== null ? ` · 状态版本：${receipt.state_version}` : ''}
            </p>
          )}
          {receipt.can_cancel && (
            <button className="bh-button" type="button" onClick={onCancelAction}>
              撤回行动
            </button>
          )}
          {receipt.status === 'awaiting_player_choice' && compositeChoice && (
            <div className="bh-muted-box">
              <strong>{compositeChoice.question}</strong>
              <div className="bh-action-row bh-action-row--responsive">
                <button className="bh-button bh-button--yellow" type="button" onClick={() => onResolveCompositeChoice(true)}>
                  继续下一步
                </button>
                <button className="bh-button" type="button" onClick={() => onResolveCompositeChoice(false)}>
                  到此为止
                </button>
              </div>
            </div>
          )}
          {ruleExplanation && (
            <dl className="bh-action-preview__facts">
              <div><dt>技能</dt><dd>{String(authoritativeInputs.skill_name ?? '无需技能')}</dd></div>
              <div><dt>目标值</dt><dd>{String(authoritativeInputs.target ?? '—')}</dd></div>
              <div><dt>难度</dt><dd>{String(ruleExplanation.modifiers.difficulty ?? 'regular')}</dd></div>
              <div><dt>骰点</dt><dd>{formatRolls(authoritativeInputs.raw_rolls)}</dd></div>
              <div><dt>成功等级</dt><dd>{String(authoritativeInputs.success_level ?? '—')}</dd></div>
            </dl>
          )}
          {ruleExplanation && (
            <details className="bh-rule-explanation">
              <summary>展开判定依据</summary>
              <dl className="bh-action-preview__facts">
                <div><dt>公式</dt><dd>{ruleExplanation.formula}</dd></div>
                <div><dt>状态前</dt><dd>{formatState(ruleExplanation.state_before)}</dd></div>
                <div><dt>状态后</dt><dd>{formatState(ruleExplanation.state_after)}</dd></div>
                <div><dt>规则版本</dt><dd>{ruleExplanation.rule_set_version}</dd></div>
              </dl>
              {ruleExplanation.hidden_sources.map((item, index) => (
                <p key={index}>隐藏来源：{String(item.effect ?? '已应用隐藏机械影响')}</p>
              ))}
              <RedactedCitationDisclosure citations={ruleExplanation.citations || []} />
            </details>
          )}
        </article>
      )}
    </section>
  );
}

function extractCompositeChoice(value: unknown): { question: string; stepId: string } | null {
  if (!value || typeof value !== 'object') return null;
  const metadata = (value as { metadata?: unknown }).metadata;
  if (!metadata || typeof metadata !== 'object') return null;
  const composite = (metadata as { composite_action?: unknown }).composite_action;
  if (!composite || typeof composite !== 'object') return null;
  const awaitingChoice = (composite as { awaiting_choice?: unknown }).awaiting_choice;
  if (!awaitingChoice || typeof awaitingChoice !== 'object') return null;
  const question = (awaitingChoice as { question?: unknown }).question;
  const stepId = (awaitingChoice as { step_id?: unknown }).step_id;
  return typeof question === 'string' && typeof stepId === 'string' ? { question, stepId } : null;
}
