import type { ReactNode } from 'react';
import { CompassIcon } from '@phosphor-icons/react/dist/csr/Compass';
import { ListIcon } from '@phosphor-icons/react/dist/csr/List';
import { MagnifyingGlassIcon } from '@phosphor-icons/react/dist/csr/MagnifyingGlass';
import { UserIcon } from '@phosphor-icons/react/dist/csr/User';
import { playerTabs, type PlayerTabKey } from '../navigation';
import type { CharacterSheet } from '../types';
import type { PlayerCurrentPriority } from '../shared/player-current-priority';
import './player-journal-shell.css';

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
  const investigatorName = character?.investigator_name || character?.name || '调查员';
  const mobileActiveTab = activeTab === 'character'
    ? 'character'
    : activeTab === 'logs'
      ? 'investigation'
      : activeTab === 'inventory' || activeTab === 'map'
        ? 'more'
        : 'current';

  return (
    <div className={`bh-player-terminal${activeTab === 'action' ? ' bh-player-terminal--journal' : ''}`}>
      <header className="bh-player-header">
        {activeTab === 'action' ? (
          <>
            <div className="bh-avatar" aria-hidden="true">
              <img src={new URL('../assets/player-journal/investigator.png', import.meta.url).href} alt="" aria-hidden="true" />
            </div>
            <div className="bh-player-identity">
              <div className="bh-player-name">{investigatorName}</div>
              <div className="bh-vitals">
                <div className="bh-vital" aria-label={`生命值 ${hp}`}>
                  <strong>HP</strong>
                  <span>{hp}</span>
                </div>
                <div className="bh-vital" aria-label={`理智值 ${san}`}>
                  <strong>SAN</strong>
                  <span>{san}</span>
                </div>
                {onToggleReady && (
                  <button
                    className="bh-button bh-player-ready"
                    onClick={onToggleReady}
                    type="button"
                  >
                    {charStatus === 'pending_approval' ? '等待批准' : isReady ? '已准备' : '准备'}
                  </button>
                )}
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="bh-avatar">ID</div>
            <div>
              <div className="bh-player-name">{character?.player_name || character?.name || 'INVESTIGATOR'}</div>
              <div className="bh-subtitle">{character ? `INVESTIGATOR / ${character.investigator_name || character.name}` : 'Arkham field terminal'}</div>
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
          </>
        )}
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
          {activeTab === 'action'
            ? <CompassIcon className="bh-tab-icon" size={26} weight="regular" aria-hidden="true" />
            : <span className="bh-tab-eyebrow">NOW</span>}
          <strong>当前</strong>
        </button>
        <button
          className="bh-tab"
          aria-selected={mobileActiveTab === 'investigation'}
          onClick={() => onTabChange('logs')}
          type="button"
        >
          {activeTab === 'action'
            ? <MagnifyingGlassIcon className="bh-tab-icon" size={26} weight="regular" aria-hidden="true" />
            : <span className="bh-tab-eyebrow">CASE</span>}
          <strong>调查</strong>
        </button>
        <button
          className="bh-tab"
          aria-selected={mobileActiveTab === 'character'}
          onClick={() => onTabChange('character')}
          type="button"
        >
          {activeTab === 'action'
            ? <UserIcon className="bh-tab-icon" size={26} weight="regular" aria-hidden="true" />
            : <span className="bh-tab-eyebrow">SHEET</span>}
          <strong>角色</strong>
        </button>
        <details className="bh-player-more" open={mobileActiveTab === 'more'}>
          <summary className="bh-tab" aria-current={mobileActiveTab === 'more' ? 'page' : undefined}>
            {activeTab === 'action'
              ? <ListIcon className="bh-tab-icon" size={26} weight="regular" aria-hidden="true" />
              : <span className="bh-tab-eyebrow">MORE</span>}
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
