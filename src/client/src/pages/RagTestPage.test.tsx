import { beforeAll, describe, expect, test } from 'vitest';

function createStorageMock(): Storage {
  const store = new Map<string, string>();
  return {
    get length() { return store.size; },
    clear() { store.clear(); },
    getItem(key) { return store.get(key) ?? null; },
    key(index) { return Array.from(store.keys())[index] ?? null; },
    removeItem(key) { store.delete(key); },
    setItem(key, value) { store.set(key, value); },
  };
}

beforeAll(() => {
  Object.defineProperty(globalThis, 'localStorage', { value: createStorageMock(), configurable: true });
  Object.defineProperty(globalThis, 'sessionStorage', { value: createStorageMock(), configurable: true });
});

async function loadRagTestPage() {
  return import('./RagTestPage');
}

describe('RagTestPage audit helpers', () => {
  test('uses the authoritative citation page instead of a chunk index', async () => {
    const { formatCitation } = await loadRagTestPage();

    expect(formatCitation({
      source_id: 'official-source',
      source_type: 'rule',
      content: '困难成功规则',
      metadata: { index: 540 },
      citation: { page_number: 358 },
    })).toBe('第 358 页');
  });

  test('summarizes the official source audit without exposing page text', async () => {
    const { summarizeAuthoritativeAudit } = await loadRagTestPage();

    expect(summarizeAuthoritativeAudit({
      version_status: 'published',
      runtime_eligible: true,
      source: { filename: 'COC7th核心规则书v1.2.1.pdf', sha256: '22F5' },
      pages: { total: 380, indexable: 376, archived_non_retrieval: 4, needs_review: 0 },
      gate: { status: 'ready' },
    })).toEqual([
      '已发布，可运行',
      '380 页（376 页可检索，4 页归档，0 页待审）',
      '审计门禁：ready',
    ]);
  });
});
