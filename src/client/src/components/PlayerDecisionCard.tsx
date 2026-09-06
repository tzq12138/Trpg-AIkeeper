import { useEffect, useState } from 'react';
import type {
  ActionConsentDTO,
  ActionConsentOutcomeDTO,
  ActionDraftDTO,
  ActionReceiptDTO,
  ActionStatus,
  CocFollowUpDTO,
  RuntimeIntegrityDTO,
} from '../shared/types';
import type { CollaborationParticipantDTO } from '../shared/player-api';
import {
  confirmationImpactSummary,
  type PlayerInputMode,
} from '../shared/player-input-modes';
import RedactedCitationDisclosure from './RedactedCitationDisclosure';
import ReviewPanel from './ReviewPanel';
import { recoveryCopy } from '../shared/review-controller';


interface PlayerDecisionCardProps {
  draft?: ActionDraftDTO | null;
  receipt?: ActionReceiptDTO | null;
  pendingConsent?: ActionConsentDTO | null;
  consentOutcome?: ActionConsentOutcomeDTO | null;
  runtimeIntegrity?: RuntimeIntegrityDTO | null;
  inputMode?: PlayerInputMode;
  speechRoutesToDialogue?: boolean;
  collaborationParticipants?: CollaborationParticipantDTO[];
  currentCharacterId?: string;
  onConfirmDraft?: (selectedSkill?: string, compositeStepOrder?: string[]) => void;
  onDiscardDraft?: () => void;
  onApplyClarification?: (candidate: NonNullable<ActionDraftDTO['candidate_interpretations']>[number]) => void;
  onCancelAction?: () => void;
  onResolveCompositeChoice?: (proceed: boolean) => void;
  onRespondConsent?: (consentId: string, accepted: boolean) => void;
  onSubmitFollowUp?: (decision: 'spend_luck' | 'push' | 'decline') => void;
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
  awaiting_player_consent: '等待受影响玩家确认',
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
  if (!Array.isArray(rawRolls)) return '—';
  return rawRolls
    .filter((roll): roll is Record<string, unknown> => Boolean(roll) && typeof roll === 'object')
    .map((roll) => `${String(roll.dice ?? 'd100')} ${String(roll.result ?? '—')}`)
    .join(' · ') || '—';
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

export function extractCocFollowUp(value: unknown): CocFollowUpDTO | null {
  if (!value || typeof value !== 'object') return null;
  const metadata = (value as { metadata?: unknown }).metadata;
  if (!metadata || typeof metadata !== 'object') return null;
  const followUp = (metadata as { follow_up?: unknown }).follow_up;
  if (!followUp || typeof followUp !== 'object') return null;
  const candidate = followUp as Partial<CocFollowUpDTO>;
  if (candidate.status !== 'pending' || !Array.isArray(candidate.allowed_decisions)) return null;
  return candidate as CocFollowUpDTO;
}

function integrityCopy(integrity: RuntimeIntegrityDTO): { title: string; detail: string } | null {
  if (integrity.status === 'paused_provider') {
    return {
      title: 'AI 服务连续失败',
      detail: '机械行动已暂停。你仍可查看记录，等待 Host 恢复原服务或显式切换 provider。',
    };
  }
  if (integrity.status === 'read_only_recovery') {
    return {
      title: '只读恢复',
      detail: '机械行动已暂停。状态完整性需要 Host 处理，当前不会写入新的世界状态。',
    };
  }
  return null;
}

function policyReason(draft: ActionDraftDTO): string | null {
  if (draft.params.policyReason === 'private_mechanical_action_forbidden') {
    return '私密机械行动不能直接改变世界状态；请公开重提，或取消且不产生任何效果。';
  }
  return null;
}

function modifierSummary(modifiers: Record<string, unknown>): string {
  const parts: string[] = [];
  if (modifiers.difficulty) parts.push(`难度 ${String(modifiers.difficulty)}`);
  const bonusDice = Number(modifiers.bonus_dice ?? 0);
  if (Number.isFinite(bonusDice) && bonusDice !== 0) {
    parts.push(`${bonusDice > 0 ? '奖励骰' : '惩罚骰'} ${Math.abs(bonusDice)}`);
  }
  return parts.join(' · ') || '无公开修正';
}


export default function PlayerDecisionCard({
  draft,
  receipt,
  pendingConsent,
  consentOutcome,
  runtimeIntegrity,
  inputMode = 'action',
  speechRoutesToDialogue = false,
  collaborationParticipants = [],
  currentCharacterId,
  onConfirmDraft = () => {},
  onDiscardDraft = () => {},
  onApplyClarification = () => {},
  onCancelAction = () => {},
  onResolveCompositeChoice = () => {},
  onRespondConsent = () => {},
  onSubmitFollowUp = () => {},
  onUpdateCollaborationDependencies = () => {},
}: PlayerDecisionCardProps) {
  const [selectedSkill, setSelectedSkill] = useState('');
  const [compositeStepOrder, setCompositeStepOrder] = useState<string[]>([]);
  const [clarificationIndex, setClarificationIndex] = useState<number | null>(null);
  const [dependencyCharacterIds, setDependencyCharacterIds] = useState<string[]>(
    () => collaborationDependencies(draft),
  );

  useEffect(() => {
    setSelectedSkill('');
    setCompositeStepOrder(draft?.composite_steps.map((step) => step.step_id) || []);
    setClarificationIndex(null);
    setDependencyCharacterIds(collaborationDependencies(draft));
  }, [draft?.draft_id, draft?.revision]);

  const integrity = runtimeIntegrity ? integrityCopy(runtimeIntegrity) : null;
  const skillChoices = draft
    ? [draft.suggested_skill, ...draft.alternative_skills].filter(
      (skill): skill is string => Boolean(skill),
    )
    : [];
  const requiresSkillChoice = Boolean(draft && draft.alternative_skills.length > 0);
  const currentCompositeOrder = draft?.composite_steps.length === 2
    ? compositeStepOrder.length === 2
      ? compositeStepOrder
      : draft.composite_steps.map((step) => step.step_id)
    : [];
  const orderedCompositeSteps = draft?.composite_steps.length === 2
    ? currentCompositeOrder.map((stepId) => draft.composite_steps.find((step) => step.step_id === stepId))
      .filter((step): step is ActionDraftDTO['composite_steps'][number] => Boolean(step))
    : [];
  const clarificationOptions = (draft?.candidate_interpretations || []).slice(0, 3);
  const isCollaborationDraft = typeof draft?.params.collaborationContractId === 'string';
  const collaborationTeammates = collaborationParticipants.filter(
    (participant) => participant.characterId !== currentCharacterId,
  );
  const ruleExplanation = receipt?.rule_explanation;
  const authoritativeInputs = ruleExplanation?.authoritative_inputs ?? {};
  const compositeChoice = extractCompositeChoice(receipt?.result);
  const followUp = extractCocFollowUp(receipt?.result);

  const toggleCollaborationDependency = (characterId: string) => {
    const nextDependencies = dependencyCharacterIds.includes(characterId)
      ? dependencyCharacterIds.filter((value) => value !== characterId)
      : [...dependencyCharacterIds, characterId];
    setDependencyCharacterIds(nextDependencies);
    onUpdateCollaborationDependencies(nextDependencies);
  };

  if (!draft && !receipt && !pendingConsent && !consentOutcome && !integrity) return null;

  return (
    <div className="bh-player-decisions" aria-label="待确认决定与权威回执">
      {integrity && (
        <article className="bh-muted-box bh-player-runtime-pause" role="status">
          <strong>{integrity.title}</strong>
          <p>{integrity.detail}</p>
          {runtimeIntegrity?.reasonCode && <code>{runtimeIntegrity.reasonCode}</code>}
        </article>
      )}

      {pendingConsent && (
        <article className="bh-action-preview bh-action-preview--high" aria-label="受影响玩家确认">
          <div className="bh-action-preview__header">
            <span className="bh-eyebrow">AFFECTED PLAYER CONSENT</span>
            <strong>只由你决定</strong>
          </div>
          <p>{pendingConsent.declaredIntent}</p>
          <p className="bh-muted-box">拒绝不会视为行动失败，也不会产生任何机械效果。</p>
          <div className="bh-action-row bh-action-row--responsive">
            <button className="bh-button bh-button--yellow" type="button" onClick={() => onRespondConsent(pendingConsent.consentId, true)}>接受影响</button>
            <button className="bh-button" type="button" onClick={() => onRespondConsent(pendingConsent.consentId, false)}>拒绝影响</button>
          </div>
        </article>
      )}

      {consentOutcome?.accepted === false && (
        <article className="bh-muted-box" role="status">
          <strong>你已拒绝，本行动不产生机械效果。</strong>
        </article>
      )}

      {draft && (
        <article className={`bh-action-preview bh-action-preview--${draft.risk}`}>
          <div className="bh-action-preview__header">
            <span className="bh-eyebrow">{draft.ephemeral ? '临时理解（不保存）' : '行动确认'}</span>
            <strong>{RISK_LABELS[draft.risk]}</strong>
          </div>
          {!draft.ephemeral && <p className="bh-muted">草稿版本：{draft.revision}</p>}
          <p>{draft.understanding_summary}</p>
          {policyReason(draft) && <p className="bh-error">{policyReason(draft)}</p>}
          {draft.intent_contract && (
            <dl className="bh-action-preview__facts">
              {draft.intent_contract.target && <div><dt>目标</dt><dd>{draft.intent_contract.target}</dd></div>}
              {draft.intent_contract.method && <div><dt>方法</dt><dd>{draft.intent_contract.method}</dd></div>}
              {draft.intent_contract.conditions.length > 0 && <div><dt>条件</dt><dd>{draft.intent_contract.conditions.join('；')}</dd></div>}
              {draft.intent_contract.ambiguities.length > 0 && <div><dt>待澄清</dt><dd>{draft.intent_contract.ambiguities.join('；')}</dd></div>}
            </dl>
          )}
          <dl className="bh-action-preview__facts">
            <div><dt>技能</dt><dd>{draft.suggested_skill || '无需技能'}</dd></div>
            <div><dt>难度</dt><dd>{draft.difficulty || '无'}</dd></div>
            {draft.resource_impacts.length > 0 && (
              <div><dt>资源影响</dt><dd>{draft.resource_impacts.map((impact, index) => (
                <span key={`${String(impact.resource || impact.label || 'resource')}-${index}`}>
                  {String(impact.label || impact.resource || '资源')}{impact.dice ? ` -${String(impact.dice)}` : ''}
                </span>
              ))}</dd></div>
            )}
            <div><dt>可见性</dt><dd>{draft.visibility}</dd></div>
            <div><dt>置信度</dt><dd>{Math.round(draft.confidence * 100)}%</dd></div>
          </dl>

          {requiresSkillChoice && (
            <div className="bh-muted-box">
              <label className="bh-field-label" htmlFor="selected-action-skill">选择采用的技能</label>
              <select id="selected-action-skill" className="bh-input" value={selectedSkill} onChange={(event) => setSelectedSkill(event.target.value)}>
                <option value="">请选择技能</option>
                {skillChoices.map((skill) => <option key={skill} value={skill}>{skill}</option>)}
              </select>
              <p>系统会以你选定的技能读取服务器角色卡数值，不能自行填写其他技能。</p>
            </div>
          )}

          {orderedCompositeSteps.length === 2 && (
            <div className="bh-muted-box">
              <strong>组合行动（同一回合，仅消耗一次行动）</strong>
              <ol>{orderedCompositeSteps.map((step, index) => (
                <li key={step.step_id}>
                  {step.summary}
                  {index === 1 && <small> · {step.execution_condition === 'previous_step_success'
                    ? '仅在第一步成功时执行'
                    : step.execution_condition === 'previous_step_failure'
                      ? '仅在第一步失败时执行'
                      : '无论第一步结果都会执行'}{step.execution_condition === 'previous_step_success' && `；第一步失败时：${
                    step.on_previous_failure === 'cancel'
                      ? '自动取消此步'
                      : step.on_previous_failure === 'ask'
                        ? '询问你是否继续'
                        : '继续尝试此步'
                  }`}</small>}
                </li>
              ))}</ol>
              <button className="bh-button" type="button" onClick={() => setCompositeStepOrder((current) => [...current].reverse())}>调整顺序</button>
            </div>
          )}

          {isCollaborationDraft && collaborationTeammates.length > 0 && (
            <div className="bh-muted-box">
              <strong>协同行动顺序</strong>
              <p>只勾选你的行动必须等待其完成的队友。若前置行动未能完成，你的行动会进入异常处理，不会自动改写结果。</p>
              {collaborationTeammates.map((participant) => (
                <label key={participant.characterId} className="bh-checkbox-row">
                  <input type="checkbox" checked={dependencyCharacterIds.includes(participant.characterId)} onChange={() => toggleCollaborationDependency(participant.characterId)} />
                  等待 {participant.playerName} 的行动
                </label>
              ))}
            </div>
          )}

          {draft.status === 'analyzing' && clarificationOptions.length > 0 && (
            <div className="bh-muted-box">
              <strong>请先选择本回合的主要事项</strong>
              <p>选择一个主要事项，保留并重新分析；未选择时不会确认或写入状态。</p>
              {clarificationOptions.map((option, index) => (
                <label className="bh-checkbox-row" key={`${option.label || 'option'}-${index}`}>
                  <input type="radio" name={`clarification-${draft.draft_id || 'ephemeral'}`} checked={clarificationIndex === index} onChange={() => setClarificationIndex(index)} />
                  {option.label || `主要事项 ${index + 1}`}
                </label>
              ))}
              <button
                className="bh-button bh-button--yellow"
                type="button"
                disabled={clarificationIndex === null}
                onClick={() => clarificationIndex !== null && onApplyClarification(clarificationOptions[clarificationIndex])}
              >
                应用选择并重新分析
              </button>
            </div>
          )}

          {draft.confirmation_requirements.length > 0 && (
            <div className="bh-confirmation-list">
              {draft.confirmation_requirements.map((requirement) => <code key={requirement}>{requirement}</code>)}
            </div>
          )}
          {draft.requires_confirmation && <p className="bh-muted-box"><strong>确认后：</strong>{confirmationImpactSummary(inputMode, speechRoutesToDialogue)}</p>}
          <RedactedCitationDisclosure citations={draft.citations || []} />
          {!draft.ephemeral && (
            <div className="bh-action-row bh-action-row--responsive">
              {draft.status === 'awaiting_confirmation' && (
                <button
                  className="bh-button bh-button--yellow"
                  type="button"
                  disabled={requiresSkillChoice && !selectedSkill}
                  onClick={() => onConfirmDraft(
                    selectedSkill || undefined,
                    orderedCompositeSteps.length === 2 ? orderedCompositeSteps.map((step) => step.step_id) : undefined,
                  )}
                >确认并提交</button>
              )}
              <button className="bh-button" type="button" onClick={onDiscardDraft}>
                {draft.status === 'analyzing' && draft.intent_contract?.ambiguities.length ? '修改描述' : '放弃草稿'}
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
          {(() => {
            const copy = recoveryCopy(receipt);
            return copy ? (
              <div className="bh-muted-box" role="status">
                <strong>{copy.title}</strong>
                <p>{copy.detail}</p>
                {copy.code && <code>{copy.code}</code>}
              </div>
            ) : null;
          })()}
          <p className="bh-muted">回执：{receipt.action_id} · 草稿版本：{receipt.revision}</p>
          <ol className="bh-action-timeline">{receipt.timeline.map((event, index) => (
            <li key={`${event.status}-${event.created_at}-${index}`}><strong>{actionStatusLabel(event.status)}</strong><time>{event.created_at}</time></li>
          ))}</ol>
          {(receipt.transaction_id || receipt.state_version !== null) && (
            <p className="bh-muted">
              {receipt.transaction_id ? `事务：${receipt.transaction_id}` : '事务：处理中'}
              {receipt.state_version !== null ? ` · 状态版本：${receipt.state_version}` : ''}
            </p>
          )}
          {receipt.can_cancel && <button className="bh-button" type="button" onClick={onCancelAction}>撤回行动</button>}

          {followUp && (
            <div className="bh-muted-box" aria-label="CoC 失败判定后续">
              <strong>初次判定失败：选择后续</strong>
              {followUp.luck?.available && followUp.allowed_decisions.includes('spend_luck') && (
                <button className="bh-button bh-button--yellow" type="button" onClick={() => onSubmitFollowUp('spend_luck')}>
                  消耗 {Number(followUp.luck.required || 0)} 点幸运
                </button>
              )}
              {followUp.push?.available && followUp.allowed_decisions.includes('push') && (
                <div>
                  <p>推骰风险（{RISK_LABELS[followUp.push.risk_level || 'high']}）：{followUp.push.warning || '再次失败将产生不可逆后果。'}</p>
                  <button className="bh-button" type="button" onClick={() => onSubmitFollowUp('push')}>确认推骰</button>
                </div>
              )}
              {followUp.allowed_decisions.includes('decline') && (
                <button className="bh-button" type="button" onClick={() => onSubmitFollowUp('decline')}>保留原失败</button>
              )}
            </div>
          )}

          {!followUp && receipt.status === 'awaiting_player_choice' && compositeChoice && (
            <div className="bh-muted-box">
              <strong>{compositeChoice.question}</strong>
              <div className="bh-action-row bh-action-row--responsive">
                <button className="bh-button bh-button--yellow" type="button" onClick={() => onResolveCompositeChoice(true)}>继续下一步</button>
                <button className="bh-button" type="button" onClick={() => onResolveCompositeChoice(false)}>到此为止</button>
              </div>
            </div>
          )}

          <ReviewPanel
            actionId={receipt.action_id}
            canReview={Boolean(receipt.can_review)}
            declaredIntent={receipt.declared_intent}
            runtime={receipt}
          />

          {ruleExplanation && (
            <>
              <dl className="bh-action-preview__facts">
                <div><dt>技能</dt><dd>{String(authoritativeInputs.skill_name ?? '无需技能')}</dd></div>
                <div><dt>目标值</dt><dd>{String(authoritativeInputs.target ?? '—')}</dd></div>
                <div><dt>允许修正</dt><dd>{modifierSummary(ruleExplanation.modifiers)}</dd></div>
                <div><dt>骰点</dt><dd>{formatRolls(authoritativeInputs.raw_rolls)}</dd></div>
                <div><dt>成功等级</dt><dd>{String(authoritativeInputs.success_level ?? '—')}</dd></div>
                <div><dt>最终 delta</dt><dd>{formatState(ruleExplanation.state_after)}</dd></div>
              </dl>
              <p className="bh-muted">规则版本：{ruleExplanation.rule_set_version}</p>
              {ruleExplanation.hidden_sources.length > 0 && (
                <p>已应用 {ruleExplanation.hidden_sources.length} 项隐藏机械影响；隐藏来源文本不会展示。</p>
              )}
              <details className="bh-rule-explanation">
                <summary>展开判定依据</summary>
                <dl className="bh-action-preview__facts">
                  <div><dt>公式</dt><dd>{ruleExplanation.formula}</dd></div>
                  <div><dt>状态前</dt><dd>{formatState(ruleExplanation.state_before)}</dd></div>
                  <div><dt>状态后</dt><dd>{formatState(ruleExplanation.state_after)}</dd></div>
                </dl>
                <RedactedCitationDisclosure citations={ruleExplanation.citations || []} />
              </details>
            </>
          )}
        </article>
      )}
    </div>
  );
}
