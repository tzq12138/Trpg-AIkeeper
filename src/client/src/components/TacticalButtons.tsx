import type { TacticalAction } from '../types';

interface TacticalButtonsProps {
  actions: TacticalAction[];
  disabled: boolean;
  onSelect: (action: TacticalAction) => void;
}

export default function TacticalButtons({ actions, disabled, onSelect }: TacticalButtonsProps) {
  if (!actions || actions.length === 0) return null;

  return (
    <div className="bh-tactical-buttons">
      {actions.map((action) => (
        <button
          key={action.action_id}
          onClick={() => !disabled && onSelect(action)}
          disabled={disabled}
          className="bh-button bh-button--black bh-tactical-button"
        >
          {action.label}
        </button>
      ))}
    </div>
  );
}
