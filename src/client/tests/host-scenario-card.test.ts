import { describe, expect, it } from 'vitest';
import { getScenarioLaunchBadge } from '../src/shared/host-scenario-card';

describe('getScenarioLaunchBadge', () => {
  it('marks warning scenarios without hiding their launch status', () => {
    expect(getScenarioLaunchBadge({ quality_level: 'warning', risk_warning: '存在质量警告' })).toEqual({
      label: '可开团 · 需留意',
      detail: '存在质量警告',
    });
  });

  it('uses the published default when no quality warning exists', () => {
    expect(getScenarioLaunchBadge({ quality_level: 'ready' })).toEqual({
      label: '已发布 · 可开团',
      detail: '版本与开团门禁已通过',
    });
  });
});
