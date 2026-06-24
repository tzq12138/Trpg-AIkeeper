# 模块 2 —— 对讲机系统与语音指令采集 (Push-to-Talk & STT Gateway) v2.0

## v2.0 修订说明：语音走 REST 意图 + 环境变量 + 文本降级

1. **语音结果走 REST 意图网关**：废弃 `engine.inject_player_message()` 的直接注入方式。STT 转写文本后，通过 `POST /api/player/intent` 以 `intentType: 'voice_command'` 提交。
2. **URL 环境变量化**：`import.meta.env.VITE_API_URL` 替代硬编码 `localhost:8000`。
3. **iOS 兼容**：检测 `MediaRecorder.isTypeSupported()` 选择兼容 MIME 类型。
4. **文本降级路径**：麦克风权限被拒时，自动展示文本输入框，不阻塞操作。
5. **Toast 替代 `alert()`**：移动端友好的提示方式。

---

### 第一部分：核心录音引擎 Hook (`useAudioRecorder.ts`)

```typescript
// src/client/player/hooks/useAudioRecorder.ts
import { useState, useRef, useCallback } from 'react';

function getSupportedMimeType(): string {
  const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/aac'];
  for (const t of types) {
    if (MediaRecorder.isTypeSupported(t)) return t;
  }
  return 'audio/webm'; // fallback
}

export function useAudioRecorder() {
  const [isRecording, setIsRecording] = useState(false);
  const [micDenied, setMicDenied] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = getSupportedMimeType();
      const mediaRecorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      mediaRecorder.start();
      setIsRecording(true);
      if (navigator.vibrate) navigator.vibrate(50);
    } catch {
      setMicDenied(true);
      console.warn('麦克风权限被拒绝，降级为文本输入模式');
    }
  }, []);

  const stopRecording = useCallback((): Promise<Blob | null> => {
    return new Promise((resolve) => {
      const mr = mediaRecorderRef.current;
      if (!mr || mr.state === 'inactive') { resolve(null); return; }

      mr.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: mr.mimeType });
        setIsRecording(false);
        mr.stream.getTracks().forEach(t => t.stop());
        resolve(blob);
      };
      mr.stop();
    });
  }, []);

  const cancelRecording = useCallback(() => {
    const mr = mediaRecorderRef.current;
    if (mr && mr.state !== 'inactive') {
      mr.onstop = null;
      mr.stop();
      mr.stream.getTracks().forEach(t => t.stop());
      setIsRecording(false);
    }
  }, []);

  return { isRecording, micDenied, startRecording, stopRecording, cancelRecording };
}
```

### 第二部分：高敏触控对讲按钮 (`PushToTalkButton.tsx`)

```typescript
// src/client/player/components/PushToTalkButton.tsx
import React, { useRef, useState } from 'react';
import { useAudioRecorder } from '../hooks/useAudioRecorder';
import { usePlayerAction } from '../hooks/usePlayerAction';
import './PushToTalk.css';

export function PushToTalkButton() {
  const { isRecording, micDenied, startRecording, stopRecording, cancelRecording } = useAudioRecorder();
  const { submitIntent, actionState } = usePlayerAction();
  const [isHoveringCancel, setIsHoveringCancel] = useState(false);
  const startYRef = useRef(0);

  const handlePointerDown = (e: React.PointerEvent) => {
    startYRef.current = e.clientY;
    startRecording();
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!isRecording) return;
    setIsHoveringCancel(startYRef.current - e.clientY > 80);
  };

  const handlePointerUp = async () => {
    if (!isRecording) return;
    if (isHoveringCancel) {
      cancelRecording();
      setIsHoveringCancel(false);
      if (navigator.vibrate) navigator.vibrate([50, 50, 50]);
    } else {
      const blob = await stopRecording();
      if (blob) await sendAudioToServer(blob);
    }
  };

  const sendAudioToServer = async (blob: Blob) => {
    const formData = new FormData();
    formData.append('audio', blob, 'voice.webm');

    try {
      const res = await fetch(`${import.meta.env.VITE_API_URL}/api/player/speech-to-text`, {
        method: 'POST',
        headers: { 'X-Room-Token': usePlayerStore.getState().roomToken },
        body: formData,
      });
      const { transcribedText } = await res.json();
      if (transcribedText) {
        // 走统一意图网关，不再直接注入 Engine
        await submitIntent('voice_command', transcribedText);
      }
    } catch (err) {
      console.error('语音发送失败', err);
      showToast('语音发送失败，请重试或使用文字输入');
    }
  };

  // 麦克风被拒时展示文本输入降级
  if (micDenied) {
    return <TextInputFallback />;
  }

  return (
    <div className="ptt-container">
      <div className={`ptt-status ${isRecording ? 'visible' : ''} ${isHoveringCancel ? 'cancel-warn' : ''}`}>
        {isHoveringCancel ? '松开取消' : '松开发送...'}
      </div>
      <button
        className={`ptt-button ${isRecording ? 'recording' : ''}`}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
        onContextMenu={e => e.preventDefault()}
        disabled={actionState !== 'IDLE'}
      >
        <span className="icon">🎤</span>
      </button>
      {isRecording && <div className="ptt-ripple-effect" />}
    </div>
  );
}

function TextInputFallback() {
  const { submitIntent, actionState } = usePlayerAction();
  const [text, setText] = useState('');

  return (
    <div className="text-fallback">
      <input
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder="输入你的行动..."
        disabled={actionState !== 'IDLE'}
      />
      <button
        disabled={!text.trim() || actionState !== 'IDLE'}
        onClick={() => { submitIntent('dialogue', text.trim()); setText(''); }}
      >发送</button>
    </div>
  );
}

function showToast(msg: string) { /* 轻量 toast 实现 */ }
```

### 模块 2 小结

语音采集逻辑保留，但上行路径改为 `STT → transcribedText → submitIntent('voice_command', text)`，统一经过 REST 意图网关。增加了 iOS MIME 兼容检测和麦克风拒绝时的文本降级路径。
