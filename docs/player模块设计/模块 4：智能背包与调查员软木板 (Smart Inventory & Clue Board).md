# 模块 4：智能背包与调查员软木板 (Smart Inventory & Clue Board) v2.0

## v2.0 修订说明：状态由 patch/snapshot 驱动 + 修复软木板位置跳变

1. **状态来源变更**：背包和线索不再由 `s2c_private_notice` 的单播 payload 直接设置，而是通过 `s2c_state_patch`（增量）或 `s2c_full_snapshot`（全量）更新 Store，由 Store 驱动 UI。
2. **软木板 `getPosition` 修复**：真正基于 `clue.id` 做确定性散列，而非基于数组 `index`。
3. **`alert()` 替换为详情 Modal**。
4. **物品交互走 REST 意图**：`use` / `show` 操作通过 `submitIntent('use_item', ...)` 提交。

---

### 第一部分：Store 中的背包与线索（已在模块 3 的 `usePlayerStore` 中定义）

```typescript
// usePlayerStore 关键字段
inventory: Item[];
clues: ClueNode[];

receiveItem: (item: Item) => void;   // 由 s2c_state_patch 调用
unlockClue: (clue: ClueNode) => void;
applyFullSnapshot: (snapshot) => ...; // 全量覆写
applyStatePatch: (patch) => ...;      // 增量更新
```

### 第二部分：智能背包 (`InventoryPanel.tsx`)

```typescript
// src/client/player/components/InventoryPanel.tsx
import React, { useState } from 'react';
import { usePlayerStore, Item } from '../store/usePlayerStore';
import { usePlayerAction } from '../hooks/usePlayerAction';

export function InventoryPanel() {
  const inventory = usePlayerStore(s => s.inventory);
  const [selectedItem, setSelectedItem] = useState<Item | null>(null);
  const { submitIntent, actionState } = usePlayerAction();

  const handleItemAction = (actionType: 'use' | 'show') => {
    if (!selectedItem || actionState !== 'IDLE') return;
    submitIntent(
      actionType === 'use' ? 'use_item' : 'show_item',
      `${actionType === 'use' ? '使用' : '展示'}【${selectedItem.name}】`,
      { itemId: selectedItem.id, action: actionType }
    );
    setSelectedItem(null);
  };

  return (
    <div className="inventory-container">
      <h3 className="panel-title">🎒 随身物品</h3>
      <div className="item-grid">
        {inventory.map(item => (
          <div
            key={item.id}
            className={`item-card ${item.isSecret ? 'secret-glow' : ''}`}
            onClick={() => setSelectedItem(item)}
          >
            <span className="item-icon">{item.iconUrl || '📦'}</span>
            <span className="item-name">{item.name}</span>
          </div>
        ))}
      </div>

      {selectedItem && (
        <div className="bottom-sheet-overlay" onClick={() => setSelectedItem(null)}>
          <div className="bottom-sheet-content" onClick={e => e.stopPropagation()}>
            <h4>{selectedItem.name} {selectedItem.isSecret && '🤫'}</h4>
            <p className="item-desc">{selectedItem.description}</p>
            <div className="action-buttons">
              <button
                disabled={actionState !== 'IDLE'}
                onClick={() => handleItemAction('use')}
              >✋ 尝试使用</button>
              <button
                disabled={actionState !== 'IDLE'}
                onClick={() => handleItemAction('show')}
              >👁️ 展示给队友</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
```

### 第三部分：调查员软木板 (`CorkboardView.tsx`)

**修复**：`getPosition` 现在真正基于 `id` 做确定性散列，不再因数组插入导致位置跳变。

```typescript
// src/client/player/components/CorkboardView.tsx
import React, { useState } from 'react';
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch';
import { usePlayerStore, ClueNode } from '../store/usePlayerStore';
import './Corkboard.css';

// 基于 id 的确定性散列 → 卡片位置永不跳变
function getPosition(id: string): { x: number; y: number; rotate: number } {
  let hash = 0;
  for (let i = 0; i < id.length; i++) {
    hash = ((hash << 5) - hash) + id.charCodeAt(i);
    hash |= 0;
  }
  return {
    x: Math.abs(hash % 400) + 20,
    y: Math.abs((hash >> 8) % 500) + 20,
    rotate: (hash % 10) - 5,
  };
}

export function CorkboardView() {
  const clues = usePlayerStore(s => s.clues);
  const [detailClue, setDetailClue] = useState<ClueNode | null>(null);

  return (
    <div className="corkboard-container">
      <h3 className="panel-title">📌 调查日志</h3>
      <TransformWrapper initialScale={1} minScale={0.5} maxScale={2}>
        <TransformComponent wrapperClass="corkboard-wrapper">
          <div className="corkboard-canvas">
            {clues.map(clue => {
              const pos = getPosition(clue.id);
              return (
                <div
                  key={clue.id}
                  className={`clue-card type-${clue.type}`}
                  style={{ transform: `translate(${pos.x}px, ${pos.y}px) rotate(${pos.rotate}deg)` }}
                  onClick={() => setDetailClue(clue)}
                >
                  <div className="clue-pin" />
                  <h5>{clue.title}</h5>
                  <span className="clue-meta">{clue.unlockedAt}</span>
                </div>
              );
            })}
          </div>
        </TransformComponent>
      </TransformWrapper>

      {/* 详情 Modal 替代 alert */}
      {detailClue && (
        <div className="clue-detail-modal" onClick={() => setDetailClue(null)}>
          <div className="clue-detail-content" onClick={e => e.stopPropagation()}>
            <h4>{detailClue.title}</h4>
            <p>{detailClue.summary}</p>
            <span className="clue-meta">{detailClue.unlockedAt}</span>
            <button onClick={() => setDetailClue(null)}>关闭</button>
          </div>
        </div>
      )}
    </div>
  );
}
```

### 模块 4 小结

背包和线索板的数据源统一为 Store 的 `s2c_state_patch` / `s2c_full_snapshot` 驱动。`getPosition` 真正基于 `clue.id` 散列，插入新线索不再导致旧卡片位移。物品交互统一走 `submitIntent`，`alert()` 替换为详情 Modal。
