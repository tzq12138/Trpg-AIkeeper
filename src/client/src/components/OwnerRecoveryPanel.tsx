import { useEffect, useState } from 'react';
import { getSlotValue } from '../shared/identity';
import {
  actionsFromResponse,
  buildExecuteBody,
  isOwnerTerminal,
  needsRecoveryPanel,
  parseErrorDetail,
  proposalIdFromCreate,
  proposalIdFromResponse,
  statusCopy,
  type RecoveryPanelState,
} from '../shared/host-recovery-controller';

const ROOM_POLL_MS = 4000;

function ownerHeaders(): Record<string, string> {
  return { 'X-Owner-Token': getSlotValue('owner_token') || '' };
}

interface OwnerRecoveryPanelProps {
  roomId: string;
}

export interface OwnerRecoveryViewProps {
  state: RecoveryPanelState;
  busy: boolean;
  endArmed: boolean;
  message: string;
  errorMessage: string;
  onGenerate: () => void;
  onDryRun: () => void;
  onExecute: () => void;
  onArmEnd: () => void;
  onCancelEnd: () => void;
  onEnd: () => void;
}

/**
 * R7 presentational Owner console (state injected; the polling wrapper below
 * owns the data). Renders nothing while the room runs.
 */
export function OwnerRecoveryView({
  state,
  busy,
  endArmed,
  message,
  errorMessage,
  onGenerate,
  onDryRun,
  onExecute,
  onArmEnd,
  onCancelEnd,
  onEnd,
}: OwnerRecoveryViewProps) {
  const copy = statusCopy(state.runtime);
  const active = needsRecoveryPanel(state.runtime) || state.phase !== 'idle';
  if (!active && !isOwnerTerminal(state.runtime) && state.runtime !== 'paused_by_owner') {
    return null;
  }
  const canExecute = state.phase === 'dry_run_verified' && state.runtime === 'paused_system';
  const endVisible = !isOwnerTerminal(state.runtime);
  return (
    <section className="bh-owner-recovery" aria-label="系统恢复与房主终止">
      {copy && (
        <div className="bh-muted-box" role="status">
          <strong>{copy.title}</strong>
          <p>{copy.detail}</p>
          {state.integrityReason && <code>{state.integrityReason}</code>}
        </div>
      )}

      {state.runtime === 'paused_system' && (
        <div className="bh-action-row bh-action-row--responsive">
          <button
            className="bh-button bh-button--yellow"
            type="button"
            disabled={busy || state.phase !== 'idle'}
            onClick={onGenerate}
          >
            生成系统恢复方案
          </button>
          {state.phase === 'proposed' && (
            <button className="bh-button" type="button" disabled={busy} onClick={onDryRun}>
              验证方案（dry-run）
            </button>
          )}
          {state.phase === 'dry_run_verified' && (
            <button className="bh-button" type="button" disabled={busy || !canExecute} onClick={onExecute}>
              执行恢复（confirm）
            </button>
          )}
        </div>
      )}

      {state.runtime === 'recovering' && (
        <p className="bh-muted">
          方案 {state.proposalId || '(执行中)'} 正在恢复
          {state.actionsToResume.length > 0 ? ` · ${state.actionsToResume.length} 个原行动续跑中` : ''}
          ——完成后房间自动回到运行。
        </p>
      )}

      {endVisible && (
        <div className="bh-owner-end" aria-label="房主正常终止">
          {!endArmed ? (
            <button className="bh-button" type="button" disabled={busy} onClick={onArmEnd}>
              正常终止本房间
            </button>
          ) : (
            <div className="bh-muted-box">
              <strong>确认终止？</strong>
              <p>AI 房间将按 aborted 归档并转为只读：不显示任何作者胜利结局，也不会生成新的世界状态。玩家可继续查看自己的记录。</p>
              <div className="bh-action-row">
                <button className="bh-button bh-button--yellow" type="button" disabled={busy} onClick={onEnd}>
                  确认终止（aborted 归档）
                </button>
                <button className="bh-button" type="button" disabled={busy} onClick={onCancelEnd}>
                  取消
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {message && <p className="bh-muted" role="status">{message}</p>}
      {errorMessage && <p className="bh-error" role="alert">{errorMessage}</p>}
    </section>
  );
}

/**
 * R7 Owner console: system-recovery controls for ai_only rooms.
 *
 * The Owner can only: (1) ask the engine to GENERATE the recovery proposal
 * from the newest verified checkpoint, (2) dry-run the SAME proposal, and
 * (3) execute it with {"confirm": true} — there is no checkpoint picker and
 * no way to nominate a replacement proposal. While the room is recovering the
 * panel only observes; a normal Owner termination (aborted archive, read-only
 * afterwards) is a separate two-step control. Stage/player identities never
 * mount this component (HostLobby is Owner-scoped) and the server enforces
 * owner/admin auth on every endpoint.
 */
export default function OwnerRecoveryPanel({ roomId }: OwnerRecoveryPanelProps) {
  const [state, setState] = useState<RecoveryPanelState>({
    runtime: 'lobby',
    integrityReason: '',
    phase: 'idle',
    proposalId: null,
    actionsToResume: [],
  });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [endArmed, setEndArmed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch(`/api/rooms/${encodeURIComponent(roomId)}`, {
          headers: ownerHeaders(),
        });
        if (!response.ok) {
          if (!cancelled) setErrorMessage(`房间状态读取失败（${response.status}）`);
          return;
        }
        const room = await response.json() as {
          runtime_status?: string;
          integrity_reason?: string;
        };
        if (cancelled) return;
        setState((previous) => {
          const runtime = String(room.runtime_status || room.runtime_status || previous.runtime);
          let phase = previous.phase;
          if (runtime === 'ended') phase = 'ended';
          else if (runtime === 'recovering') phase = previous.phase === 'executing' ? 'executing' : 'executing';
          else if (runtime === 'running' && previous.phase === 'executing') phase = 'done';
          else if (runtime !== 'paused_system' && runtime !== 'recovering') phase = 'idle';
          return {
            runtime,
            integrityReason: String(room.integrity_reason || ''),
            phase,
            proposalId: previous.proposalId,
            actionsToResume: previous.actionsToResume,
          };
        });
        setErrorMessage('');
      } catch {
        if (!cancelled) setErrorMessage('房间状态暂时不可用，将自动重试。');
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), ROOM_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [roomId]);

  const ownerFetch = async (path: string, init: RequestInit = {}) => {
    const response = await fetch(path, {
      ...init,
      headers: { ...ownerHeaders(), ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    });
    const payload: unknown = await response.json().catch(() => undefined);
    if (!response.ok) {
      throw Object.assign(new Error('owner request failed'), {
        status: response.status,
        detail: payload,
      });
    }
    return payload;
  };

  const generateProposal = async () => {
    setBusy(true);
    setErrorMessage('');
    setMessage('');
    try {
      const body = await ownerFetch(
        `/api/rooms/${encodeURIComponent(roomId)}/recovery/proposals`,
        { method: 'POST' },
      );
      const proposalId = proposalIdFromCreate(body);
      setState((previous) => ({
        ...previous,
        phase: proposalId ? 'proposed' : 'idle',
        proposalId,
      }));
      if (!proposalId) setErrorMessage('系统未返回方案 ID，请刷新后重试。');
    } catch (error) {
      setErrorMessage(parseErrorDetail(error));
    } finally {
      setBusy(false);
    }
  };

  const dryRunProposal = async () => {
    if (!state.proposalId) return;
    setBusy(true);
    setErrorMessage('');
    setMessage('');
    try {
      await ownerFetch(
        `/api/rooms/${encodeURIComponent(roomId)}/recovery/proposals/${encodeURIComponent(state.proposalId)}/dry-run`,
        { method: 'POST' },
      );
      setState((previous) => ({ ...previous, phase: 'dry_run_verified' }));
    } catch (error) {
      setErrorMessage(parseErrorDetail(error));
    } finally {
      setBusy(false);
    }
  };

  const executeProposal = async () => {
    if (!state.proposalId) return;
    setBusy(true);
    setErrorMessage('');
    setMessage('');
    try {
      const body = await ownerFetch(
        `/api/rooms/${encodeURIComponent(roomId)}/recovery/proposals/${encodeURIComponent(state.proposalId)}/execute`,
        { method: 'POST', body: JSON.stringify(buildExecuteBody()) },
      );
      const proposalId = proposalIdFromResponse(body) || state.proposalId;
      setState((previous) => ({
        ...previous,
        phase: 'executing',
        proposalId,
        actionsToResume: actionsFromResponse(body),
      }));
      setMessage(
        `恢复执行已开始，原行动（${(actionsFromResponse(body) || []).length} 个）将在恢复完成后回到同一回执。`,
      );
    } catch (error) {
      setErrorMessage(parseErrorDetail(error));
    } finally {
      setBusy(false);
    }
  };

  const endRoom = async () => {
    setBusy(true);
    setErrorMessage('');
    setMessage('');
    try {
      const body = await ownerFetch(`/api/rooms/${encodeURIComponent(roomId)}/end`, {
        method: 'POST',
      }) as { status?: string; ending_status?: string; termination_reason?: string };
      setState((previous) => ({ ...previous, runtime: 'ended', phase: 'ended' }));
      setMessage(
        body.ending_status === 'aborted'
          ? '房间已正常终止并归档（aborted，只读）。'
          : `房间已结束（${String(body.status || 'ended')}）。`,
      );
    } catch (error) {
      setErrorMessage(parseErrorDetail(error));
    } finally {
      setBusy(false);
      setEndArmed(false);
    }
  };

  return (
    <OwnerRecoveryView
      state={state}
      busy={busy}
      endArmed={endArmed}
      message={message}
      errorMessage={errorMessage}
      onGenerate={() => void generateProposal()}
      onDryRun={() => void dryRunProposal()}
      onExecute={() => void executeProposal()}
      onArmEnd={() => setEndArmed(true)}
      onCancelEnd={() => setEndArmed(false)}
      onEnd={() => void endRoom()}
    />
  );
}
