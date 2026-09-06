/**
 * R7 owner-console recovery controller: pure logic for the system-recovery
 * flow (proposal -> dry-run -> execute) and the normal Owner termination of
 * an ai_only room. All decisions follow the server contract: the Owner only
 * confirms the system-generated proposal (never picks a checkpoint), execute
 * always carries {"confirm": true}, and a normal end archives as
 * aborted/owner_terminated with no fabricated ending.
 */

export type RoomRuntimeStatus =
  | 'lobby'
  | 'running'
  | 'paused_by_owner'
  | 'paused_system'
  | 'recovering'
  | 'ended'
  | string;

export interface RecoveryPanelState {
  runtime: RoomRuntimeStatus;
  integrityReason: string;
  phase: 'idle' | 'proposed' | 'dry_run_verified' | 'executing' | 'done' | 'ended';
  proposalId: string | null;
  actionsToResume: string[];
}

export const ROOM_STATUS_COPY: Record<string, { title: string; detail: string }> = {
  paused_system: {
    title: '系统暂停',
    detail: '房间因系统完整性问题暂停。原行动与已提交结果已保留；请生成系统恢复方案。',
  },
  recovering: {
    title: '恢复执行中',
    detail: '系统正在按已验证方案恢复原行动。恢复完成前玩家不可提交新行动。',
  },
  running: {
    title: '运行中',
    detail: '世界状态可写，玩家可正常行动。',
  },
  ended: {
    title: '已归档（只读）',
    detail: '本房间已由房主正常终止并归档，仅可只读查看。',
  },
  paused_by_owner: {
    title: '房主暂停',
    detail: '房主暂停生效中；恢复后玩家可继续。',
  },
};

export function statusCopy(runtime: RoomRuntimeStatus): { title: string; detail: string } | null {
  const key = String(runtime || '');
  return ROOM_STATUS_COPY[key] ?? null;
}

export function needsRecoveryPanel(runtime: RoomRuntimeStatus): boolean {
  return runtime === 'paused_system' || runtime === 'recovering';
}

export function isOwnerTerminal(runtime: RoomRuntimeStatus): boolean {
  return runtime === 'ended';
}

/** Owner only ever confirms the system-generated proposal. */
export function buildExecuteBody(): { confirm: true } {
  return { confirm: true };
}

export function proposalIdFromCreate(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null;
  const proposal = (body as { proposal?: unknown }).proposal;
  if (!proposal || typeof proposal !== 'object') return null;
  const id = (proposal as { proposal_id?: unknown }).proposal_id;
  return typeof id === 'string' && id ? id : null;
}

export function proposalIdFromResponse(body: unknown): string | null {
  if (!body || typeof body !== 'object') return null;
  const id = (body as { proposal_id?: unknown }).proposal_id;
  return typeof id === 'string' && id ? id : null;
}

export function actionsFromResponse(body: unknown): string[] {
  if (!body || typeof body !== 'object') return [];
  const ids = (body as { actions_to_resume?: unknown }).actions_to_resume;
  return Array.isArray(ids) ? ids.filter((id): id is string => typeof id === 'string') : [];
}

export function parseErrorDetail(error: unknown): string {
  if (!error) return '操作失败，请重试';
  if (typeof error === 'string') return error;
  const candidate = error as { detail?: unknown; message?: unknown; status?: unknown };
  if (candidate && candidate.detail && typeof candidate.detail === 'object') {
    const structured = candidate.detail as { code?: unknown; reason?: unknown };
    const code = typeof structured.code === 'string' ? structured.code : null;
    const reason = typeof structured.reason === 'string' ? structured.reason : null;
    if (code) return reason ? `${code}（${reason}）` : code;
  }
  if (candidate && typeof candidate.detail === 'string') return candidate.detail;
  const message = candidate?.message;
  if (typeof message === 'string' && message) return message;
  return `请求失败（HTTP ${String(candidate?.status ?? '?')}）`;
}
