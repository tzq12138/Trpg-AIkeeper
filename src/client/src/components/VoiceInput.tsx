import { useState, useRef, useCallback } from 'react';
import { getSlotValue } from '../shared/identity';

type State = 'idle' | 'recording' | 'uploading' | 'transcribed';

interface TranscriptResult {
  text: string;
  confidence?: number;
  provider?: string;
}

interface Props {
  onSendToTeam: (text: string, source: 'voice' | 'text') => void;
  onSubmitAction: (text: string) => void;
}

export default function VoiceInput({ onSendToTeam, onSubmitAction }: Props) {
  const [state, setState] = useState<State>('idle');
  const [transcript, setTranscript] = useState<TranscriptResult | null>(null);
  const [error, setError] = useState('');
  const [editedText, setEditedText] = useState('');
  const [uploadProgress, setUploadProgress] = useState('');

  const mediaRecorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startY = useRef(0);
  const cancelled = useRef(false);
  const mimeType = useRef('');

  const getPreferredMime = () => {
    const types = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/aac'];
    for (const t of types) {
      if (MediaRecorder.isTypeSupported(t)) return t;
    }
    return '';
  };

  const startRecording = useCallback(async () => {
    setError('');
    setTranscript(null);
    cancelled.current = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = getPreferredMime();
      mimeType.current = mime;
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      mediaRecorder.current = recorder;
      chunks.current = [];

      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (cancelled.current) { setState('idle'); return; }
        setState('uploading');
        setUploadProgress('上传中...');
        const blob = new Blob(chunks.current, { type: mimeType.current || 'audio/webm' });
        await uploadAudio(blob);
      };
      recorder.start();
      setState('recording');
    } catch (err: any) {
      if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
        setError('麦克风权限被拒绝。请使用文本输入。');
      } else {
        setError('无法启动录音: ' + (err.message || ''));
      }
    }
  }, []);

  const stopRecording = useCallback((clientY?: number, startYVal?: number) => {
    if (startYVal && clientY && startYVal - clientY > 80) {
      cancelled.current = true;
    }
    if (mediaRecorder.current && mediaRecorder.current.state === 'recording') {
      mediaRecorder.current.stop();
    }
  }, []);

  const uploadAudio = async (blob: Blob) => {
    const token = getSlotValue('player_token') || '';
    const fd = new FormData();
    fd.append('audio', blob, 'recording.' + (mimeType.current.includes('webm') ? 'webm' : 'mp4'));
    try {
      const res = await fetch('/api/player/speech-to-text', {
        method: 'POST', headers: { 'X-Room-Token': token }, body: fd,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (res.status === 503) {
          setError('语音转写未配置。请使用文本输入。');
        } else {
          setError(err.detail || '转写失败');
        }
        setState('idle');
        return;
      }
      const data = await res.json();
      const text = data.transcribedText || '';
      setTranscript({ text, confidence: data.confidence, provider: data.provider });
      setEditedText(text);
      setState('transcribed');
    } catch {
      setError('网络错误，转写失败');
      setState('idle');
    }
  };

  const handleSendToTeam = () => {
    const text = editedText.trim();
    if (!text) return;
    onSendToTeam(text, transcript ? 'voice' : 'text');
    reset();
  };

  const handleSubmitAction = () => {
    const text = editedText.trim();
    if (!text) return;
    onSubmitAction(text);
    reset();
  };

  const reset = () => {
    setState('idle');
    setTranscript(null);
    setEditedText('');
    setError('');
    setUploadProgress('');
  };

  // ── Preview card (after transcription) ──
  if (state === 'transcribed' && transcript) {
    return (
      <div className="bh-panel" style={{ marginBottom: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
          <span className="bh-eyebrow" style={{ fontSize: 9 }}>语音转写{transcript.provider ? ` · ${transcript.provider}` : ''}{transcript.confidence ? ` · ${Math.round(transcript.confidence * 100)}%` : ''}</span>
          <button className="bh-button" style={{ padding: '2px 8px', fontSize: 10 }} onClick={reset}>✕ 取消</button>
        </div>
        <textarea
          className="bh-textarea"
          rows={3}
          value={editedText}
          onChange={(e) => setEditedText(e.target.value)}
          style={{ marginBottom: 8 }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="bh-button bh-button--blue" onClick={handleSendToTeam}>📢 发给队伍</button>
          <button className="bh-button bh-button--yellow" onClick={handleSubmitAction}>⚡ 提交行动</button>
        </div>
      </div>
    );
  }

  // ── Uploading state ──
  if (state === 'uploading') {
    return (
      <div style={{ marginBottom: 8 }}>
        <div className="bh-muted-box" style={{ textAlign: 'center' }}>
          {uploadProgress}
        </div>
      </div>
    );
  }

  // ── Error display ──
  if (error) {
    return (
      <div style={{ marginBottom: 8 }}>
        <div className="bh-muted-box" style={{ color: 'var(--bh-red)', fontSize: 12 }}>
          {error}
          <button className="bh-button" style={{ marginLeft: 8, padding: '2px 8px', fontSize: 10 }}
                  onClick={() => setError('')}>关闭</button>
        </div>
      </div>
    );
  }

  // ── Default: PTT button ──
  return (
    <button
      className={`bh-button ${state === 'recording' ? 'bh-button--red' : 'bh-button--black'}`}
      style={{ width: '100%', padding: '14px', fontSize: 16, fontWeight: 900 }}
      onMouseDown={(e) => { startY.current = e.clientY; startRecording(); }}
      onMouseUp={(e) => stopRecording(e.clientY, startY.current)}
      onMouseLeave={() => { if (state === 'recording') stopRecording(); }}
      onTouchStart={(e) => { startY.current = e.touches[0].clientY; startRecording(); }}
      onTouchEnd={(e) => stopRecording(e.changedTouches[0].clientY, startY.current)}
      onTouchMove={(e) => { if (startY.current - e.touches[0].clientY > 80) cancelled.current = true; }}
    >
      {state === 'recording' ? '🎙️ 录音中... 松开发送 / 上滑取消' : '🎤 按住说话'}
    </button>
  );
}
