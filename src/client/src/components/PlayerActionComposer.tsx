import type { ActionDraftDTO, ActionReceiptDTO, ActionStatus } from '../shared/types';
import RedactedCitationDisclosure from './RedactedCitationDisclosure';


interface PlayerActionComposerProps {
  inputText: string;
  phase: ActionStatus;
  draft?: ActionDraftDTO | null;
  ephemeralPreview?: ActionDraftDTO | null;
  receipt?: ActionReceiptDTO | null;
  error?: string;
  onInputChange: (value: string) => void;
  onAnalyze: () => void;
  onConfirm: () => void;
  onDiscard: () => void;
  onCancelAction: () => void;
}

const RISK_LABELS = {
  low: '低风险',
  medium: '中风险',
  high: '高风险',
} as const;


export default function PlayerActionComposer({
  inputText,
  phase,
  draft,
  ephemeralPreview,
  receipt,
  error,
  onInputChange,
  onAnalyze,
  onConfirm,
  onDiscard,
  onCancelAction,
}: PlayerActionComposerProps) {
  const preview = draft || ephemeralPreview;
  const editingDisabled = phase === 'analyzing' || Boolean(draft) || Boolean(
    receipt && !['completed', 'resolved', 'rejected', 'canceled', 'timeout'].includes(receipt.status),
  );

  return (
    <section className="bh-action-composer" aria-label="玩家行动编辑器">
      <div className="bh-action-box">
        <textarea
          className="bh-textarea"
          value={inputText}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder="描述你的行动..."
          disabled={editingDisabled}
        />
        <div className="bh-action-row bh-action-row--responsive">
          <button
            className="bh-button bh-button--yellow"
            type="button"
            onClick={onAnalyze}
            disabled={!inputText.trim() || editingDisabled}
          >
            {phase === 'analyzing' ? '分析中...' : '生成行动预览'}
          </button>
          <span className="bh-action-phase" aria-live="polite">{phase}</span>
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
          <dl className="bh-action-preview__facts">
            <div><dt>技能</dt><dd>{preview.suggested_skill || '无需技能'}</dd></div>
            <div><dt>难度</dt><dd>{preview.difficulty || '无'}</dd></div>
            <div><dt>可见性</dt><dd>{preview.visibility}</dd></div>
            <div><dt>置信度</dt><dd>{Math.round(preview.confidence * 100)}%</dd></div>
          </dl>
          {preview.confirmation_requirements.length > 0 && (
            <div className="bh-confirmation-list">
              {preview.confirmation_requirements.map((requirement) => (
                <code key={requirement}>{requirement}</code>
              ))}
            </div>
          )}
          <RedactedCitationDisclosure citations={preview.citations || []} />
          {draft && (
            <div className="bh-action-row bh-action-row--responsive">
              <button className="bh-button bh-button--yellow" type="button" onClick={onConfirm}>
                确认并提交
              </button>
              <button className="bh-button" type="button" onClick={onDiscard}>
                放弃草稿
              </button>
            </div>
          )}
        </article>
      )}

      {receipt && (
        <article className="bh-action-receipt" aria-live="polite">
          <div className="bh-action-preview__header">
            <span className="bh-eyebrow">ACTION RECEIPT</span>
            <strong>{receipt.status}</strong>
          </div>
          <ol className="bh-action-timeline">
            {receipt.timeline.map((event, index) => (
              <li key={`${event.status}-${event.created_at}-${index}`}>
                <strong>{event.status}</strong>
                <time>{event.created_at}</time>
              </li>
            ))}
          </ol>
          {receipt.can_cancel && (
            <button className="bh-button" type="button" onClick={onCancelAction}>
              撤回行动
            </button>
          )}
          {receipt.rule_explanation && (
            <details className="bh-rule-explanation">
              <summary>展开判定依据</summary>
              <dl className="bh-action-preview__facts">
                <div><dt>公式</dt><dd>{receipt.rule_explanation.formula}</dd></div>
                <div><dt>规则版本</dt><dd>{receipt.rule_explanation.rule_set_version}</dd></div>
              </dl>
              {receipt.rule_explanation.hidden_sources.map((item, index) => (
                <p key={index}>隐藏来源：{String(item.effect ?? '已应用隐藏机械影响')}</p>
              ))}
              <RedactedCitationDisclosure citations={receipt.rule_explanation.citations || []} />
            </details>
          )}
        </article>
      )}
    </section>
  );
}
