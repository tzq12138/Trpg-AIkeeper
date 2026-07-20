export type AbsentPolicy = 'idle' | 'maintain_existing';

export default function AbsentPolicyControl({
  policy,
  disabled = false,
  onChange,
}: {
  policy: AbsentPolicy;
  disabled?: boolean;
  onChange: (policy: AbsentPolicy) => void;
}) {
  return (
    <section className="bh-muted-box" aria-label="缺席策略">
      <span className="bh-eyebrow">ABSENCE POLICY</span>
      <h3>缺席策略</h3>
      <p>声明窗口超时后使用。不会自动攻击、选目标、花资源或承担额外风险。</p>
      <div className="bh-hint-list">
        <button
          className="bh-button"
          type="button"
          aria-pressed={policy === 'idle'}
          disabled={disabled}
          onClick={() => onChange('idle')}
        >
          本轮暂不主动行动
        </button>
        <button
          className="bh-button"
          type="button"
          aria-pressed={policy === 'maintain_existing'}
          disabled={disabled}
          onClick={() => onChange('maintain_existing')}
        >
          维持既有持续行为
        </button>
      </div>
    </section>
  );
}
