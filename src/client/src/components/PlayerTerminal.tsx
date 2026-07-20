import type { ReactNode } from 'react';
import { playerTabs, type PlayerTabKey } from '../navigation';
import type { CharacterSheet } from '../types';
import type { PlayerCurrentPriority } from '../shared/player-current-priority';

interface PlayerTerminalProps {
  activeTab: PlayerTabKey;
  character: CharacterSheet | null;
  children: ReactNode;
  onTabChange: (tab: PlayerTabKey) => void;
  isReady?: boolean;
  charStatus?: string;
  onToggleReady?: () => void;
  currentPriority?: PlayerCurrentPriority;
  pendingTaskCount?: number;
}

export default function PlayerTerminal({ activeTab, character, children, onTabChange, isReady, charStatus, onToggleReady, currentPriority, pendingTaskCount = 0 }: PlayerTerminalProps) {
  const hp = character ? `${character.hp}/${character.max_hp}` : '--/--';
  const san = character ? `${character.san}/${character.max_san}` : '--/--';
  const playerName = character?.player_name || character?.name || 'INVESTIGATOR';
  const investigatorName = character?.investigator_name || character?.name || '';
  const mobileActiveTab = activeTab === 'character'
    ? 'character'
    : activeTab === 'logs'
      ? 'investigation'
      : activeTab === 'inventory' || activeTab === 'map'
        ? 'more'
        : 'current';

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

      {activeTab !== 'action' && currentPriority && (
        <section className={`bh-muted-box bh-player-current bh-player-current--${currentPriority.kind}`} aria-label="当前最重要的事">
          <span className="bh-eyebrow">CURRENT PRIORITY</span>
          <strong>{currentPriority.title}</strong>
          <p>{currentPriority.detail}</p>
          {pendingTaskCount > 1 && <p>另有 {pendingTaskCount - 1} 项待处理。</p>}
          <button className="bh-button" type="button" onClick={() => onTabChange(currentPriority.targetTab || 'action')}>
            {currentPriority.targetTab === 'inventory'
              ? '查看背包'
              : currentPriority.targetTab === 'home'
                ? '查看战役回流'
                : currentPriority.targetTab === 'logs'
                  ? '查看记录'
                  : '回到当前'}
          </button>
        </section>
      )}

      <main className="bh-player-content">{children}</main>

      <nav className="bh-player-tabs bh-player-tabs--desktop" aria-label="玩家终端导航">
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

      <nav className="bh-player-tabs bh-player-tabs--mobile" aria-label="玩家手机导航">
        <button
          className="bh-tab"
          aria-selected={mobileActiveTab === 'current'}
          onClick={() => onTabChange('action')}
          type="button"
        >
          <span className="bh-tab-eyebrow">NOW</span>
          <strong>当前</strong>
        </button>
        <button
          className="bh-tab"
          aria-selected={mobileActiveTab === 'investigation'}
          onClick={() => onTabChange('logs')}
          type="button"
        >
          <span className="bh-tab-eyebrow">CASE</span>
          <strong>调查</strong>
        </button>
        <button
          className="bh-tab"
          aria-selected={mobileActiveTab === 'character'}
          onClick={() => onTabChange('character')}
          type="button"
        >
          <span className="bh-tab-eyebrow">SHEET</span>
          <strong>角色</strong>
        </button>
        <details className="bh-player-more" open={mobileActiveTab === 'more'}>
          <summary className="bh-tab" aria-current={mobileActiveTab === 'more' ? 'page' : undefined}>
            <span className="bh-tab-eyebrow">MORE</span>
            <strong>更多</strong>
          </summary>
          <div className="bh-player-more__menu">
            <button className="bh-button" type="button" onClick={() => onTabChange('home')}>回流</button>
            <button className="bh-button" type="button" onClick={() => onTabChange('inventory')}>装备</button>
            <button className="bh-button" type="button" onClick={() => onTabChange('map')}>地图</button>
          </div>
        </details>
      </nav>
    </div>
  );
}
