import { apiFetch, authHeaders } from '../api';
import type { TacticalAction } from '../types';

interface TacticalButtonsProps {
  actions: TacticalAction[];
  disabled: boolean;
  onSubmitted?: () => void;
}

export default function TacticalButtons({ actions, disabled, onSubmitted }: TacticalButtonsProps) {
  const handleClick = async (action: TacticalAction) => {
    if (disabled) return;
    try {
      await apiFetch('/api/player/intent', {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({
          action_id: crypto.randomUUID(),
          intent_type: action.intent_type,
          declared_intent: action.label,
          params: action.params,
        }),
      });
      onSubmitted?.();
    } catch {
      // ignore
    }
  };

  if (!actions || actions.length === 0) return null;

  return (
    <div className="bh-tactical-buttons">
      {actions.map((action) => (
        <button
          key={action.action_id}
          onClick={() => handleClick(action)}
          disabled={disabled}
          className="bh-button bh-button--black bh-tactical-button"
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
