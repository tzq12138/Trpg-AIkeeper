# 模块 5 —— 剧情流式渲染与舞台演出 (Narrative & Stage Presentation) v2.0

## v2.0 修订说明：数据落库解耦 + requestAnimationFrame 打字机

1. **命名统一**：`narrative_stream` → `narrative_text`，与投影矩阵和协议对齐。
2. **数据落库模式**：场景背景、HUD、字幕文本均存入全局 Store，舞台组件（`SceneBackground`、`TypewriterSubtitle`）**永不卸载**，只被动响应 Store 变化。
3. **3D 骰子条件挂载**：`currentRollEvent` 非空时才渲染 `Dice3DNode`，停稳即销毁。
4. **requestAnimationFrame 打字机**：替代 `setInterval`，用 Ref 镜像隔离消除闭包陈旧和 Strict Mode 双激活问题。
5. **`scene_transition` step 支持**：`SceneBackground` 实现双图层交叉淡入淡出。
6. **`HostMinimalConsole`**：提供音频解锁和紧急重置的隐式控制台。

---

### 第一部分：舞台总控 (`StageRenderer.tsx`)

```typescript
// src/client/host/components/Stage/StageRenderer.tsx
import React from 'react';
import { useHostStore } from '../../store/useHostStore';
import { useTransactionPlayer } from '../../hooks/useTransactionPlayer';
import { SceneBackground } from './SceneBackground';
import { GlobalHUD } from '../GlobalHUD';
import { TypewriterSubtitle } from './TypewriterSubtitle';
import { Dice3DNode } from './nodes/Dice3DNode';

export function StageRenderer() {
  const { notifyDiceSettled } = useTransactionPlayer();
  const currentRollEvent = useHostStore(s => s.currentRollEvent);

  return (
    <div className="host-cinema-stage">
      {/* 1. 永不卸载的动态双图层背景 */}
      <SceneBackground />

      {/* 2. 永不卸载的全局 HUD */}
      <GlobalHUD />

      {/* 3. 打字机字幕区（数据来自 Store，独立 rAF 驱动） */}
      <TypewriterSubtitle />

      {/* 4. 3D 骰子层：有事件才挂载，停稳即销毁 */}
      {currentRollEvent && (
        <Dice3DNode
          rollEvent={currentRollEvent}
          onAnimationComplete={notifyDiceSettled}
        />
      )}

      {/* 5. 隐式控制台 */}
      <HostMinimalConsole />
    </div>
  );
}

function HostMinimalConsole() {
  const reset = useHostStore(s => s.resetRoomStore);
  return (
    <div className="host-hidden-console">
      <button onClick={() => {
        const ctx = new (window.AudioContext || (window as any).webkitAudioContext)();
        console.log('[Audio] 用户手势已激活:', ctx.state);
      }}>🔊 解锁音频</button>
      <button onClick={reset}>🚨 紧急重置</button>
    </div>
  );
}
```

### 第二部分：动态布景系统 (`SceneBackground.tsx`)

```typescript
// src/client/host/components/Stage/SceneBackground.tsx
import React, { useEffect, useState } from 'react';
import { useHostStore } from '../../store/useHostStore';
import './Stage.css';

export function SceneBackground() {
  const currentImageUrl = useHostStore(s => s.currentSceneImageUrl);
  const [images, setImages] = useState<string[]>([]);

  useEffect(() => {
    if (!currentImageUrl) return;
    setImages(prev => {
      const next = [...prev, currentImageUrl];
      return next.length > 2 ? next.slice(-2) : next;
    });
  }, [currentImageUrl]);

  return (
    <div className="scene-background-container">
      {images.map((url) => (
        <div
          key={url}
          className="bg-layer"
          style={{ backgroundImage: `url(${url})` }}
        />
      ))}
      <div className="fog-overlay" />
    </div>
  );
}
```

CSS 实现双图层交叉淡入淡出（`fadeIn` / `fadeOut` 3s ease）。key 使用 `url` 而非 `url + index`，避免数组重排导致 React reconciliation 问题。

### 第三部分：requestAnimationFrame 打字机 (`TypewriterSubtitle.tsx`)

```typescript
// src/client/host/components/Stage/TypewriterSubtitle.tsx
import React, { useEffect, useState, useRef } from 'react';
import { useHostStore } from '../../store/useHostStore';

export function TypewriterSubtitle() {
  const chatMessages = useHostStore(s => s.chatMessages);

  // 合并 KP/NPC 文本
  const targetText = chatMessages
    .filter(m => m.role === 'keeper' || m.role === 'npc')
    .map(m => m.speakerName ? `${m.speakerName}："${m.text}"` : m.text)
    .join('\n\n');

  const [displayedText, setDisplayedText] = useState('');
  const rafRef = useRef<number | null>(null);
  const lastTimeRef = useRef<number>(0);
  const stateRef = useRef({ displayedText, targetText });
  stateRef.current = { displayedText, targetText };

  useEffect(() => {
    // 已打印完毕则停止循环，等待 targetText 变化后重新唤醒
    if (displayedText.length >= targetText.length) return;

    const loop = (timestamp: number) => {
      if (!lastTimeRef.current) lastTimeRef.current = timestamp;
      const elapsed = timestamp - lastTimeRef.current;

      if (elapsed >= 40) {
        const { displayedText: cur, targetText: target } = stateRef.current;
        if (cur.length < target.length) {
          setDisplayedText(prev => prev + target.charAt(prev.length));
          lastTimeRef.current = timestamp;
        }
      }

      // 只在还有未打印字符时请求下一帧
      if (stateRef.current.displayedText.length < stateRef.current.targetText.length) {
        rafRef.current = requestAnimationFrame(loop);
      } else {
        rafRef.current = null;
      }
    };

    rafRef.current = requestAnimationFrame(loop);
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [targetText]); // 依赖 targetText，新文本到达时自动重新唤醒

  // 当 chatMessages 被清空时，重置打字机
  useEffect(() => {
    if (chatMessages.length === 0) setDisplayedText('');
  }, [chatMessages.length]);

  return (
    <div className="cinema-subtitle-box">
      <div className="cinema-subtitle-inner">
        {displayedText}
        <span className="cursor-pulse">▎</span>
      </div>
    </div>
  );
}
```

### 模块 5 小结

舞台总控只需挂载一次，所有演出状态在 Store 中流转。打字机用 `requestAnimationFrame` + Ref 镜像彻底消除了 `setInterval` 泄漏和闭包陈旧问题。`SceneBackground` 的 key 策略修正了 React reconciliation 隐患。
