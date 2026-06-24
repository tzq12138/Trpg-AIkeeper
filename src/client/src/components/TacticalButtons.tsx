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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
      {actions.map((action) => (
        <button
          key={action.action_id}
          onClick={() => handleClick(action)}
          disabled={disabled}
          style={{
            padding: '10px 14px',
            borderRadius: 8,
            border: '1px solid #3f51b5',
            background: disabled ? '#222' : 'rgba(63,81,181,0.15)',
            color: disabled ? '#555' : '#8c9eff',
            fontSize: 14,
            cursor: disabled ? 'not-allowed' : 'pointer',
            textAlign: 'left',
          }}
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
