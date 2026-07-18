import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeAll, beforeEach, describe, expect, test } from 'vitest';

type AdminDashboardModule = typeof import('../src/pages/AdminDashboard');

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() {
      return store.size;
    },
    clear() {
      store.clear();
    },
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    key(index: number) {
      return Array.from(store.keys())[index] ?? null;
    },
    removeItem(key: string) {
      store.delete(key);
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
  };
}

async function loadAdminDashboard(): Promise<AdminDashboardModule> {
  return import('../src/pages/AdminDashboard');
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', {
    value: createStorageMock(),
    configurable: true,
  });
  Object.defineProperty(globalThis, 'sessionStorage', {
    value: createStorageMock(),
    configurable: true,
  });
});

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
});

describe('AdminDashboard scenario import management', () => {
  test('renders map draft generation and confirmation controls inside scenario review', async () => {
    const {
      MapBaseAssetControl,
      MapDraftReviewPanel,
      buildScenarioMapGenerateEndpoint,
    } = await loadAdminDashboard();
    const html = renderToStaticMarkup(
      <MapDraftReviewPanel scenarioId="scenario-1" scenarioVersionId="version-2" assets={[]} />,
    );
    const assetControl = renderToStaticMarkup(
      <MapBaseAssetControl
        assets={[{
          asset_id: 'map-asset',
          original_name: '地图.png',
          mime_type: 'image/png',
        }]}
        disabled={false}
        selectedAssetId="map-asset"
        onChange={() => {}}
      />,
    );

    expect(html).toContain('地图草稿');
    expect(html).toContain('生成地图草稿');
    expect(html).toContain('确认地图');
    expect(html).toContain('区域与路径仅在备团阶段由管理员审核。');
    expect(assetControl).toContain('地图底图');
    expect(assetControl).toContain('地图.png');
    expect(assetControl).toContain('value="map-asset" selected=""');
    expect(buildScenarioMapGenerateEndpoint('scenario-1', 'version-2')).toBe(
      '/api/admin/scenarios/scenario-1/map/generate?scenario_version_id=version-2',
    );
  });

  test('renders review controls for a suggested scenario asset binding', async () => {
    const { AssetBindingReviewCard, ScenarioAssetBindingsPanel } = await loadAdminDashboard();
    const card = renderToStaticMarkup(
      <AssetBindingReviewCard
        binding={{
          binding_id: 'binding-1',
          asset_id: 'bus-image',
          original_name: '长途车.png',
          target_type: 'branch_node',
          target_key: '1',
          confidence: 0.91,
          evidence: { method: 'content_match' },
          generated_by: 'gateway',
          status: 'draft',
        }}
        disabled={false}
        scenarioId="scenario-1"
        targets={[
          { target_type: 'branch_node', target_key: '1', label: '条目 1' },
          { target_type: 'item', target_key: 'ticket', label: '车票' },
        ]}
        onReview={() => {}}
      />,
    );
    const panel = renderToStaticMarkup(
      <ScenarioAssetBindingsPanel scenarioId="scenario-1" scenarioVersionId="version-2" />,
    );

    expect(card).toContain('长途车.png');
    expect(card).toContain('91%');
    expect(card).toContain('条目 1');
    expect(card).toContain('确认绑定');
    expect(card).toContain('拒绝');
    expect(card).toContain('content_match');
    expect(panel).toContain('图片素材绑定');
    expect(panel).toContain('自动匹配素材');
  });

  test('renders multimodal import control with multiple file support', async () => {
    const {
      SCENARIO_IMPORT_ACCEPT,
      SCENARIO_IMPORT_ENDPOINT,
      SCENARIO_ROOM_OPTIONS_ENDPOINT,
      ScenariosPanel,
    } = await loadAdminDashboard();
    const html = renderToStaticMarkup(<ScenariosPanel />);

    expect(SCENARIO_IMPORT_ENDPOINT).toBe('/api/scenarios/import');
    expect(SCENARIO_ROOM_OPTIONS_ENDPOINT).toBe('/api/scenarios/available');
    expect(SCENARIO_IMPORT_ACCEPT).toBe('.pdf,.docx,.png,.jpg,.jpeg,.webp');
    expect(html).toContain(`accept="${SCENARIO_IMPORT_ACCEPT}"`);
    expect(html).toContain('multiple=""');
    expect(html).toContain('<option value="authorized" selected="">authorized</option>');
    expect(html).toContain('<option value="open">open</option>');
    expect(html).not.toContain('public_domain');
    expect(html).not.toContain('owned');
  });

  test('builds multipart payload with multiple files and review metadata', async () => {
    const { buildScenarioImportFormData } = await loadAdminDashboard();
    const form = buildScenarioImportFormData({
      files: [
        new Blob(['first page'], { type: 'application/pdf' }),
        new Blob(['second page'], { type: 'image/png' }),
      ],
      title: '钟楼疑云',
      licenseType: 'authorized',
      licenseRef: '授权邮件#42',
    });

    const entries = Array.from(form.entries());
    expect(entries.filter(([key]) => key === 'files')).toHaveLength(2);
    expect(form.get('title')).toBe('钟楼疑云');
    expect(form.get('license_type')).toBe('authorized');
    expect(form.get('license_ref')).toBe('授权邮件#42');
  });

  test('normalizes backend job_ids and restores retry state from scenario rows', async () => {
    const {
      chooseScenarioImportResult,
      normalizeScenarioImportResult,
      recoverScenarioImportResult,
    } = await loadAdminDashboard();

    expect(normalizeScenarioImportResult({
      status: 'awaiting_provider',
      job_ids: ['job-42'],
      scenario_id: 'sc-1',
    }).job_id).toBe('job-42');
    expect(recoverScenarioImportResult({
      scenario_id: 'sc-1',
      import_status: 'awaiting_provider',
      latest_import_job_id: 'job-42',
      latest_import_job_status: 'awaiting_provider',
    }).job_id).toBe('job-42');
    expect(recoverScenarioImportResult({
      scenario_id: 'sc-2',
      import_status: 'parsing',
      latest_import_job_id: 'job-stale',
      latest_import_job_status: 'structuring',
      latest_import_job_retryable: true,
    })).toMatchObject({
      job_id: 'job-stale',
      status: 'structuring',
      retryable: true,
    });
    expect(chooseScenarioImportResult(
      {
        scenario_id: 'sc-2',
        scenario_version_id: 'version-1',
        status: 'draft_ready',
      },
      {
        scenario_id: 'sc-2',
        job_id: 'job-stale',
        status: 'structuring',
        retryable: true,
      },
      'sc-2',
    )).toMatchObject({
      scenario_version_id: 'version-1',
      status: 'draft_ready',
    });
    expect(chooseScenarioImportResult(
      {
        scenario_id: 'other-scenario',
        job_id: 'other-job',
        status: 'awaiting_provider',
      },
      null,
      'sc-2',
    )).toBeNull();
  });

  test('redacts local and network file paths from scenario errors', async () => {
    const { sanitizeAdminScenarioError } = await loadAdminDashboard();
    const message = sanitizeAdminScenarioError(
      '导入失败：读取 C:\\secret\\draft\\module.pdf 与 \\\\nas\\share\\scene.docx 出错，缓存位于 /private/tmp/run.log',
    );

    expect(message).not.toContain('C:\\secret');
    expect(message).not.toContain('\\\\nas\\share');
    expect(message).not.toContain('/private/tmp/run.log');
    expect(message).toContain('[已隐藏路径]');
  });

  test('renders version review summary with risks, citations, and publish confirmation gate', async () => {
    const { ScenarioVersionInspector } = await loadAdminDashboard();
    const html = renderToStaticMarkup(
      <ScenarioVersionInspector
        scenarioTitle="钟楼疑云"
        versionDetail={{
          scenario_version_id: 'sv-2',
          version_number: 2,
          status: 'draft',
          is_active: false,
          published_at: '',
          quality_report: {
            level: 'warning',
            summary: '线索引用缺失，需要人工复核',
            issues: ['线索引用缺失'],
          },
          prep_package: {
            summary: '调查员将探索钟楼并寻找黑钥匙。',
            scenes: [{ name: '钟楼大厅' }, { name: '地下密室' }],
            npcs: [{ name: '守钟人' }],
            clues: [{ name: '黑钥匙' }],
            citations: [{ source_ref: 'page:3', excerpt: '黑钥匙藏在祭坛下。' }],
          },
        }}
        publishChecked={false}
        publishNotes="已核对主要线索"
        publishing={false}
        onPublishCheckedChange={() => {}}
        onPublishNotesChange={() => {}}
        onPublish={() => {}}
      />,
    );

    expect(html).toContain('draft');
    expect(html).toContain('线索引用缺失');
    expect(html).toContain('page:3');
    expect(html).toContain('确认后发布');
    expect(html).toContain('type="checkbox"');
    expect(html).toContain('disabled=""');
  });

  test('shows retry recognition action for awaiting provider jobs without leaking paths', async () => {
    const { ScenarioImportStatusCard } = await loadAdminDashboard();
    const html = renderToStaticMarkup(
      <ScenarioImportStatusCard
        importResult={{
          status: 'awaiting_provider',
          job_id: 'job-42',
          scenario_id: 'sc-1',
        }}
        retrying={false}
        retryError="失败：无法访问 C:\\secret\\draft\\module.pdf"
        onRetry={() => {}}
      />,
    );

    expect(html).toContain('重试识别');
    expect(html).toContain('job-42');
    expect(html).not.toContain('C:\\secret');
    expect(html).toContain('[已隐藏路径]');
  });

  test('shows retry recognition action for interrupted structuring jobs', async () => {
    const { ScenarioImportStatusCard } = await loadAdminDashboard();
    const html = renderToStaticMarkup(
      <ScenarioImportStatusCard
        importResult={{
          status: 'structuring',
          job_id: 'job-stale',
          scenario_id: 'sc-2',
          retryable: true,
        }}
        retrying={false}
        retryError=""
        onRetry={() => {}}
      />,
    );

    expect(html).toContain('重试识别');
    expect(html).toContain('job-stale');
  });

  test('maps structured and import workflow statuses to readable labels', async () => {
    const { getScenarioStatusMeta } = await loadAdminDashboard();
    expect(getScenarioStatusMeta('structured').label).toBe('已结构化');
    expect(getScenarioStatusMeta('awaiting_provider').label).toBe('等待上游处理');
    expect(getScenarioStatusMeta('published').label).toBe('已发布');
  });
});

describe('AdminDashboard AI provider management', () => {
  test('renders the secure provider form from the system tools area', async () => {
    const {
      ADMIN_TABS,
      AI_PROVIDER_ENDPOINT,
      AiProviderPanel,
    } = await loadAdminDashboard();
    const html = renderToStaticMarkup(
      <AiProviderPanel
        initialProviders={[{
          provider_config_id: 'provider-1',
          name: '本地多模态',
          api_base_url: 'http://127.0.0.1:8008/v1',
          protocol: 'responses',
          model: 'gpt-5.4',
          supports_image: true,
          has_api_key: true,
          key_mask: '••••1234',
          is_active: false,
          test_status: 'passed',
          last_tested_at: '2026-07-10T08:00:00Z',
          last_test_latency_ms: 42,
        }]}
      />,
    );

    expect(AI_PROVIDER_ENDPOINT).toBe('/api/admin/ai/providers');
    expect(ADMIN_TABS.some((tab) => tab.key === 'systemTools' && tab.label === '系统工具')).toBe(true);
    expect(html).toContain('API Base URL');
    expect(html).toContain('type="password"');
    expect(html).toContain('value="gpt-5.4"');
    expect(html).toContain('<option value="responses" selected="">Responses</option>');
    expect(html).toContain('<option value="chat_completions">Chat Completions</option>');
    expect(html).toContain('支持图片');
    expect(html).toContain('••••1234');
    expect(html).toContain('保存');
    expect(html).toContain('测试连接');
    expect(html).toContain('设为启用');
    expect(html).not.toContain('api_key_ciphertext');
  });
});
