import type { HostTabKey } from '../navigation';
import EncounterPanel from './EncounterPanel';
import HostLogsPanel from './HostLogsPanel';
import HostMapPanel from './HostMapPanel';

interface HostSkeletonPanelsProps {
  activeTab: HostTabKey;
  queueStatus?: { normal: number; urgent: number };
  messages: Array<{ text?: string; content?: string; speaker?: string }>;
  roomId: string;
  activeEncounter?: any;
  encounterSuggestion?: any;
  onEncounterConfirmed?: () => void;
  mapRefresh?: number;
}

export default function HostSkeletonPanels({
  activeTab, queueStatus, messages,
  roomId, activeEncounter, encounterSuggestion, onEncounterConfirmed,
  mapRefresh = 0,
}: HostSkeletonPanelsProps) {
  if (activeTab === 'combat') {
    return (
      <EncounterPanel
        roomId={roomId}
        activeEncounter={activeEncounter || null}
        encounterSuggestion={encounterSuggestion || null}
        onEncounterConfirmed={onEncounterConfirmed || (() => {})}
      />
    );
  }

  if (activeTab === 'database') {
    return (
      <div className="bh-skeleton-grid">
        <section className="bh-panel">
          <span className="bh-eyebrow">ARKHAM OS</span>
          <h2 className="bh-panel-title">资料库</h2>
          {['星之眷族', '米斯卡托尼克大学', '闪耀的偏方三八面体', '修格斯'].map((entry) => (
            <div className="bh-skeleton-row" key={entry}>
              <strong>{entry}</strong>
              <span>数据加载</span>
            </div>
          ))}
        </section>
      </div>
    );
  }

  if (activeTab === 'map') {
    return (
      <div className="bh-skeleton-grid">
        <HostMapPanel roomId={roomId} mapRefresh={mapRefresh} />
      </div>
    );
  }

  if (activeTab === 'logs') {
    return (
      <div className="bh-skeleton-grid">
        <HostLogsPanel roomId={roomId} />
      </div>
    );
  }

  // Unknown tab — show placeholder, NOT logs
  return (
    <div className="bh-skeleton-grid">
      <section className="bh-panel">
        <span className="bh-eyebrow">PANEL</span>
        <h2 className="bh-panel-title">面板未配置</h2>
        <p style={{ color: 'var(--bh-dim)' }}>Tab "{activeTab}" 尚未实现。</p>
      </section>
    </div>
  );
}
