# 模块 4 —— 独立的多感官环境渲染层 (Atmosphere Engine) v2.0

## v2.0 修订说明：字段对齐 + 音频解锁 + 音效队列修复

1. **字段统一 camelCase**：`trackId` / `fadeInMs` / `durationMs` 与协议 §7 对齐。
2. **音频解锁**：Host 大屏启动时需用户手势激活 `AudioContext`，提供显式的解锁按钮（`HostMinimalConsole`）。
3. **SFX 队列消费**：`playSFX` 改为异步等待后调用 `shiftSfx()`，避免旧版竞态条件。
4. **AI 无权操纵氛围**：`s2c_atmosphere` 仅由 Engine 广播，AI 只能提交氛围建议。

---

### 第一部分：状态（已在模块 2 Store 中定义，此处仅展示相关片段）

```typescript
// useHostStore 中的氛围相关字段（模块 2 已完整定义）
atmosphere: {
  visual: {
    filter?: 'deep_red' | 'cold_blue' | 'sepia' | 'darkness';
    vignette?: number;
    shake?: { intensity: 'low' | 'medium' | 'high'; durationMs: number };
    glitch?: boolean;
  };
  bgm: {
    trackId: string | null;
    volume: number;
    fadeInMs: number;
  };
  sfxQueue: { clipId: string; volume?: number }[];
};

setAtmosphere: (payload) => ...;
shiftSfx: () => ...;
```

### 第二部分：视觉覆盖层 (`AtmosphereOverlay.tsx`)

```typescript
// src/client/host/components/AtmosphereOverlay.tsx
import React, { useEffect, useState } from 'react';
import { useHostStore } from '../store/useHostStore';
import './AtmosphereOverlay.css';

export function AtmosphereOverlay() {
  const visual = useHostStore(state => state.atmosphere.visual);
  const [isShaking, setIsShaking] = useState(false);

  useEffect(() => {
    if (visual.shake) {
      setIsShaking(true);
      const timer = setTimeout(() => setIsShaking(false), visual.shake.durationMs);
      return () => clearTimeout(timer);
    }
  }, [visual.shake]);

  const classNames = [
    'atmosphere-overlay',
    visual.filter ? `filter-${visual.filter}` : '',
    visual.glitch ? 'glitch-effect' : '',
    isShaking && visual.shake ? `shake-${visual.shake.intensity}` : '',
  ].filter(Boolean).join(' ');

  return (
    <div className={classNames} aria-hidden="true">
      {visual.glitch && <div className="noise-layer" />}
    </div>
  );
}
```

CSS 保持不变（全屏 `pointer-events: none` 穿透层、滤镜 `mix-blend-mode`、震动关键帧、故障撕裂特效）。

### 第三部分：独立音频混音器 (`AudioMixer.ts`)

```typescript
// src/client/host/audio/AudioMixer.ts
import { Howl, Howler } from 'howler';

const AUDIO_ASSETS = {
  bgm: {
    investigation: '/assets/audio/bgm_investigation.mp3',
    combat: '/assets/audio/bgm_combat_chase.mp3',
    madness: '/assets/audio/bgm_insanity.mp3',
  },
  sfx: {
    heartbeat: '/assets/audio/sfx_heartbeat_fast.mp3',
    boneSnap: '/assets/audio/sfx_bone_snap.mp3',
    monsterRoar: '/assets/audio/sfx_roar.mp3',
  },
};

export class AudioMixer {
  private static instance: AudioMixer;
  private currentBgm: Howl | null = null;
  private currentTrackId: string | null = null;

  private constructor() {
    Howler.volume(1.0);
  }

  public unlockByUserGesture() {
    if (Howler.ctx?.state === 'suspended') {
      Howler.ctx.resume();
    }
  }

  public static getInstance(): AudioMixer {
    if (!AudioMixer.instance) AudioMixer.instance = new AudioMixer();
    return AudioMixer.instance;
  }

  public playBGM(trackId: string, volume = 0.5, fadeInMs = 2000) {
    if (this.currentTrackId === trackId) return;

    const src = AUDIO_ASSETS.bgm[trackId as keyof typeof AUDIO_ASSETS.bgm];
    if (!src) { console.warn(`未找到 BGM: ${trackId}`); return; }

    const nextBgm = new Howl({ src: [src], loop: true, volume: 0 });

    if (this.currentBgm) {
      const old = this.currentBgm;
      old.fade(old.volume(), 0, fadeInMs);
      old.once('fade', () => old.unload());
    }

    nextBgm.play();
    nextBgm.fade(0, volume, fadeInMs);
    this.currentBgm = nextBgm;
    this.currentTrackId = trackId;
  }

  public playSFX(clipId: string, volume = 0.8) {
    const src = AUDIO_ASSETS.sfx[clipId as keyof typeof AUDIO_ASSETS.sfx];
    if (!src) return;
    const sfx = new Howl({ src: [src], volume });
    sfx.play();
    sfx.on('end', () => sfx.unload());
  }
}
```

### 第四部分：音频桥接 Hook (`useAudioController.ts`)

```typescript
// src/client/host/hooks/useAudioController.ts
import { useEffect, useRef } from 'react';
import { useHostStore } from '../store/useHostStore';
import { AudioMixer } from '../audio/AudioMixer';

export function useAudioController() {
  const bgm = useHostStore(s => s.atmosphere.bgm);
  const sfxQueue = useHostStore(s => s.atmosphere.sfxQueue);
  const shiftSfx = useHostStore(s => s.shiftSfx);
  const processingRef = useRef(false);

  // BGM 切换
  useEffect(() => {
    if (bgm.trackId) {
      AudioMixer.getInstance().playBGM(bgm.trackId, bgm.volume, bgm.fadeInMs);
    }
  }, [bgm.trackId, bgm.volume, bgm.fadeInMs]);

  // SFX 队列顺序消费（修复竞态）
  useEffect(() => {
    if (sfxQueue.length === 0 || processingRef.current) return;
    processingRef.current = true;
    const clip = sfxQueue[0];
    const sfx = new (await import('howler')).Howl({
      src: [AUDIO_ASSETS.sfx[clip.clipId]],
      volume: clip.volume ?? 0.8,
      onend: () => {
        shiftSfx();
        processingRef.current = false;
      },
      onloaderror: () => {
        shiftSfx();
        processingRef.current = false;
      },
    });
    sfx.play();
  }, [sfxQueue]);
}
```

### 模块 4 小结

视觉覆盖层和音频混音器的核心逻辑未变，v2.0 主要修复了字段命名、音频解锁手势、SFX 队列的竞态条件。AI 对氛围只有建议权，最终广播由 Engine 决定。
