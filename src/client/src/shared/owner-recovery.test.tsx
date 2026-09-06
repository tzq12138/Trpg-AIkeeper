// @vitest-environment jsdom

/**
 * R7 owner-console contract: the system-recovery console appears only for
 * paused_system/recovering (plus paused_by_owner/ended notices), the Owner
 * only ever confirms the system-generated proposal with {"confirm": true},
 * and a normal end is an explicit two-step control. Stage/player identities
 * never mount this component — HostLobby is Owner-scoped and the server
 * enforces owner/admin auth on every endpoint.
 */

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  OwnerRecoveryView,
  type OwnerRecoveryViewProps,
} from '../components/OwnerRecoveryPanel';
import {
  buildExecuteBody,
  needsRecoveryPanel,
  parseErrorDetail,
  proposalIdFromCreate,
  proposalIdFromResponse,
  statusCopy,
  type RecoveryPanelState,
} from './host-recovery-controller';

function baseProps(
  state: Partial<RecoveryPanelState> = {},
  view: Partial<OwnerRecoveryViewProps> = {},
): OwnerRecoveryViewProps {
  return {
    state: {
      runtime: 'paused_system',
      integrityReason: 'narrator_timeout',
      phase: 'idle',
      proposalId: null,
      actionsToResume: [],
      ...state,
    },
    busy: false,
    endArmed: false,
    message: '',
    errorMessage: '',
    onGenerate: () => {},
    onDryRun: () => {},
    onExecute: () => {},
    onArmEnd: () => {},
    onCancelEnd: () => {},
    onEnd: () => {},
    ...view,
  };
}

describe('owner recovery panel visibility', () => {
  it('renders nothing while the room runs', () => {
    const markup = renderToStaticMarkup(<OwnerRecoveryView {...baseProps({ runtime: 'running', phase: 'idle' })} />);
    expect(markup).toBe('');
  });

  it('renders the recovery console for paused_system with the reason code', () => {
    const markup = renderToStaticMarkup(<OwnerRecoveryView {...baseProps()} />);
    expect(markup).toContain('生成系统恢复方案');
    expect(markup).toContain('narrator_timeout');
    expect(markup).toContain('系统暂停');
    expect(markup).toContain('正常终止本房间');
  });

  it('moves through proposed -> dry_run_verified button states', () => {
    const proposed = renderToStaticMarkup(<OwnerRecoveryView {...baseProps({ phase: 'proposed', proposalId: 'proposal-1' })} />);
    expect(proposed).toContain('验证方案（dry-run）');
    expect(proposed).not.toContain('执行恢复（confirm）');
    const verified = renderToStaticMarkup(
      <OwnerRecoveryView {...baseProps({ phase: 'dry_run_verified', proposalId: 'proposal-1' })} />,
    );
    expect(verified).toContain('执行恢复（confirm）');
  });

  it('renders the recovery progress view while recovering', () => {
    const markup = renderToStaticMarkup(
      <OwnerRecoveryView {...baseProps({ runtime: 'recovering', phase: 'executing', proposalId: 'proposal-1', actionsToResume: ['action-a'] })} />,
    );
    expect(markup).toContain('恢复执行中');
    expect(markup).toContain('proposal-1');
    expect(markup).toContain('1 个原行动续跑中');
    expect(markup).not.toContain('生成系统恢复方案');
  });

  it('requires a second arm step before any termination text appears', () => {
    const idle = renderToStaticMarkup(<OwnerRecoveryView {...baseProps()} />);
    expect(idle).not.toContain('确认终止（aborted 归档）');
    const armed = renderToStaticMarkup(<OwnerRecoveryView {...baseProps({}, { endArmed: true })} />);
    expect(armed).toContain('确认终止（aborted 归档）');
    expect(armed).toContain('aborted');
  });

  it('renders the ended archive notice read-only (no controls)', () => {
    const markup = renderToStaticMarkup(
      <OwnerRecoveryView {...baseProps({ runtime: 'ended', phase: 'ended' })} />,
    );
    expect(markup).toContain('已归档（只读）');
    expect(markup).not.toContain('正常终止本房间');
    expect(markup).not.toContain('生成系统恢复方案');
  });
});

describe('proposal flow helpers', () => {
  it('extracts proposal ids from create and execute responses', () => {
    expect(proposalIdFromCreate({ proposal: { proposal_id: 'proposal-1', proposal_hash: 'h' } }))
      .toBe('proposal-1');
    expect(proposalIdFromCreate({ status: 'proposed' })).toBeNull();
    expect(proposalIdFromResponse({ status: 'recovering', proposal_id: 'proposal-1' }))
      .toBe('proposal-1');
    expect(proposalIdFromResponse({ status: 'running' })).toBeNull();
  });

  it('execute always carries the confirm contract', () => {
    expect(buildExecuteBody()).toEqual({ confirm: true });
  });

  it('only the recovery states need the panel', () => {
    expect(needsRecoveryPanel('paused_system')).toBe(true);
    expect(needsRecoveryPanel('recovering')).toBe(true);
    expect(needsRecoveryPanel('running')).toBe(false);
    expect(needsRecoveryPanel('ended')).toBe(false);
  });

  it('formats structured owner errors without [object Object]', () => {
    expect(parseErrorDetail({
      status: 409,
      detail: { code: 'recovery_dry_run_required', reason: '请先验证方案' },
    })).toBe('recovery_dry_run_required（请先验证方案）');
    expect(parseErrorDetail({ status: 500, detail: { nested: true } }))
      .toContain('HTTP 500');
  });

  it('provides copy for every relevant runtime state', () => {
    expect(statusCopy('paused_system')?.title).toBe('系统暂停');
    expect(statusCopy('recovering')?.title).toBe('恢复执行中');
    expect(statusCopy('ended')?.title).toBe('已归档（只读）');
    expect(statusCopy('running')?.title).toBe('运行中');
    expect(statusCopy('lobby')).toBeNull();
  });
});
