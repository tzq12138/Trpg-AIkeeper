import type { ReactNode } from 'react';
import { playerTabs, type PlayerTabKey } from '../navigation';
import type { CharacterSheet } from '../types';

interface PlayerTerminalProps {
  activeTab: PlayerTabKey;
  character: CharacterSheet | null;
  children: ReactNode;
  onTabChange: (tab: PlayerTabKey) => void;
  isReady?: boolean;
  charStatus?: string;
  onToggleReady?: () => void;
}

export default function PlayerTerminal({ activeTab, character, children, onTabChange, isReady, charStatus, onToggleReady }: PlayerTerminalProps) {
  const hp = character ? `${character.hp}/${character.max_hp}` : '--/--';
  const san = character ? `${character.san}/${character.max_san}` : '--/--';
  const playerName = character?.player_name || character?.name || 'INVESTIGATOR';
  const investigatorName = character?.investigator_name || character?.name || '';

  return (
    <div className="bh-player-terminal">
      <header className="bh-player-header">
        <div className="bh-avatar">ID</div>
        <div>
          <div className="bh-player-name">{playerName}</div>
          <div className="bh-subtitle">{investigatorName ? `INVESTIGATOR / ${investigatorName}` : 'Arkham field terminal'}</div>
        </div>
        <div className="bh-vitals" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div>生命: {hp}</div>
          <div>理智: {san}</div>
          {onToggleReady && (
            <button
              className="bh-button"
              style={{ minHeight: 26, fontSize: 11, padding: '2px 8px', marginTop: 4 }}
              onClick={onToggleReady}
            >
              {charStatus === 'pending_approval' ? '⏳ 等待批准' : isReady ? '✅ 已准备' : '❌ 准备'}
            </button>
          )}
        </div>
      </header>

      <main className="bh-player-content">{children}</main>

      <nav className="bh-player-tabs" aria-label="玩家终端导航">
        {playerTabs.map((tab) => (
          <button
            key={tab.key}
            className="bh-tab"
            aria-selected={activeTab === tab.key}
            onClick={() => onTabChange(tab.key)}
            type="button"
          >
            <span className="bh-tab-eyebrow">{tab.eyebrow}</span>
            <strong>{tab.label}</strong>
          </button>
        ))}
      </nav>
    </div>
  );
}
