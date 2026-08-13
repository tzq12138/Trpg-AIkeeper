import { useEffect, useState } from 'react';
import { getSlotValue } from '../shared/identity';
import {
  evaluateGoldenRagQuestion,
  RAG_GOLDEN_QUESTIONS,
  type GoldenRagQuestion,
} from '../shared/rag-acceptance';

type RuleDoc = {
  doc_id: string;
  title: string;
  category: string;
  content_chars: number;
  chunks: number;
};

type RagResult = {
  source_id: string;
  source_type: string;
  content: string;
  metadata?: { title?: string; index?: number; total?: number; page?: number } | string;
  citation?: { page_number?: number } | string;
  similarity?: number;
};

type AuthoritativeAudit = {
  version_status: string;
  runtime_eligible: boolean;
  source: { filename: string; sha256: string };
  pages: {
    total: number;
    indexable: number;
    archived_non_retrieval: number;
    needs_review: number;
  };
  gate: { status: string };
};

const SAMPLE_QUERIES = RAG_GOLDEN_QUESTIONS.map((question) => question.query);

function authHeaders(): Record<string, string> {
  const token = getSlotValue('account_token') || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...authHeaders(), ...opts?.headers },
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as any).detail || `${res.status}`);
  }
  return res.json();
}

export default function RagTestPage() {
  const [docs, setDocs] = useState<RuleDoc[]>([]);
  const [authoritativeAudit, setAuthoritativeAudit] = useState<AuthoritativeAudit | null>(null);
  const [query, setQuery] = useState(SAMPLE_QUERIES[0]);
  const [results, setResults] = useState<RagResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [goldenResults, setGoldenResults] = useState<Record<string, { passed: boolean; citation_found: boolean; result_count: number }>>({});

  const loadDocs = async () => {
    try {
      setDocs(await api<RuleDoc[]>('/api/rag/rule-docs'));
    } catch {
      setError('无法读取规则书列表，请确认后端已启动。');
    }
  };

  const loadAuthoritativeAudit = async () => {
    try {
      setAuthoritativeAudit(await api<AuthoritativeAudit>('/api/rag/coc7/authoritative-audit'));
    } catch {
      setAuthoritativeAudit(null);
    }
  };

  useEffect(() => {
    loadDocs();
    loadAuthoritativeAudit();
  }, []);

  const search = async (nextQuery = query, goldenQuestion?: GoldenRagQuestion) => {
    if (!nextQuery.trim()) return;
    setQuery(nextQuery);
    setLoading(true);
    setError('');
    try {
      const data = await api<RagResult[]>('/api/rag/search', {
        method: 'POST',
        body: JSON.stringify({
          query: nextQuery,
          source_types: ['rule'],
          top_k: 5,
        }),
      });
      setResults(data);
      if (goldenQuestion) {
        const evaluation = evaluateGoldenRagQuestion(goldenQuestion, data);
        setGoldenResults((current) => ({ ...current, [goldenQuestion.id]: evaluation }));
      }
    } catch {
      setError('检索失败，请确认 RAG 后端可用。');
    } finally {
      setLoading(false);
    }
  };

  const completedGoldenCount = Object.keys(goldenResults).length;
  const passedGoldenCount = Object.values(goldenResults).filter((result) => result.passed).length;

  return (
    <div style={page}>
      <header style={header}>
        <div>
          <h1 style={title}>规则书 RAG 测试台</h1>
          <div style={subtitle}>黄金问题必须同时命中预期规则要点，并返回可定位的 citation。</div>
          <div style={{ ...subtitle, color: '#f5c542', fontWeight: 700 }}>
            黄金通过率：{passedGoldenCount} / {RAG_GOLDEN_QUESTIONS.length}（已执行 {completedGoldenCount}）
          </div>
        </div>
        <a href="/admin" style={backLink}>返回系统工具</a>
      </header>

      <section style={section}>
        <h2 style={sectionTitle}>黄金问题验收</h2>
        <div style={docGrid}>
          {RAG_GOLDEN_QUESTIONS.map((question) => {
            const outcome = goldenResults[question.id];
            return (
              <article key={question.id} style={{ ...docCard, borderColor: outcome?.passed ? '#4caf50' : outcome ? '#ef5350' : '#262626' }}>
                <div style={docTitle}>{question.query}</div>
                <div style={docMeta}>期望：{question.expected}</div>
                <div style={docStats}>
                  <span>{outcome ? (outcome.passed ? '通过' : '未通过') : '未执行'}</span>
                  <span>{outcome?.citation_found ? 'citation 已定位' : '待 citation'}</span>
                </div>
                <button onClick={() => search(question.query, question)} disabled={loading} style={{ ...sampleButton, marginTop: 10 }}>
                  执行此题
                </button>
              </article>
            );
          })}
        </div>
      </section>

      <section style={section}>
        <h2 style={sectionTitle}>正式 CoC7 规则源审计</h2>
        {authoritativeAudit ? (
          <div style={docCard}>
            <div style={docTitle}>{authoritativeAudit.source.filename}</div>
            {summarizeAuthoritativeAudit(authoritativeAudit).map((summary) => (
              <div key={summary} style={docMeta}>{summary}</div>
            ))}
            <div style={{ ...docMeta, wordBreak: 'break-all' }}>
              SHA-256：{authoritativeAudit.source.sha256}
            </div>
          </div>
        ) : (
          <div style={muted}>未读取到正式规则书审计；此信息仅管理员可见。</div>
        )}
      </section>

      <section style={section}>
        <h2 style={sectionTitle}>历史规则书索引（仅供维护）</h2>
        {docs.length === 0 ? (
          <div style={muted}>还没有读到规则书索引。</div>
        ) : (
          <div style={docGrid}>
            {docs.map((doc) => (
              <div key={doc.doc_id} style={docCard}>
                <div style={docTitle}>{doc.title}</div>
                <div style={docMeta}>{doc.category}</div>
                <div style={docStats}>
                  <span>{doc.chunks} chunks</span>
                  <span>{doc.content_chars.toLocaleString()} 字符</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <section style={section}>
        <h2 style={sectionTitle}>提问测试</h2>
        <div style={sampleRow}>
          {SAMPLE_QUERIES.map((sample) => (
            <button key={sample} onClick={() => search(sample, RAG_GOLDEN_QUESTIONS.find((question) => question.query === sample))} style={sampleButton}>
              {sample}
            </button>
          ))}
        </div>
        <div style={searchRow}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && search()}
            placeholder="输入 COC 规则问题..."
            style={input}
          />
          <button onClick={() => search()} disabled={loading} style={primaryButton}>
            {loading ? '检索中...' : '检索规则书'}
          </button>
        </div>
        {error && <div style={errorText}>{error}</div>}
      </section>

      <section style={section}>
        <h2 style={sectionTitle}>命中片段</h2>
        {results.length === 0 ? (
          <div style={muted}>输入问题后，这里会显示 top 5 命中片段。</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {results.map((result, index) => {
              const metadata = parseMetadata(result.metadata);
              return (
                <article key={`${result.source_id}-${index}`} style={resultCard}>
                  <div style={resultHead}>
                    <strong>#{index + 1}</strong>
                    <span>{metadata.title || result.source_id}</span>
                    <span>citation：{formatCitation(result)}</span>
                    <span>sim {typeof result.similarity === 'number' ? result.similarity.toFixed(4) : '-'}</span>
                  </div>
                  <p style={snippet}>{result.content}</p>
                </article>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

function parseMetadata(metadata: RagResult['metadata']) {
  if (!metadata) return {};
  if (typeof metadata === 'string') {
    try {
      return JSON.parse(metadata);
    } catch {
      return {};
    }
  }
  return metadata;
}

function parseCitation(citation: RagResult['citation']) {
  if (!citation) return {};
  if (typeof citation === 'string') {
    try {
      return JSON.parse(citation) as { page_number?: number };
    } catch {
      return {};
    }
  }
  return citation;
}

export function formatCitation(result: RagResult): string {
  const citation = parseCitation(result.citation);
  if (typeof citation.page_number === 'number') return `第 ${citation.page_number} 页`;
  const metadata = parseMetadata(result.metadata);
  if (typeof metadata.page === 'number') return `第 ${metadata.page} 页`;
  return `chunk ${metadata.index ?? '-'} / ${metadata.total ?? '-'}`;
}

export function summarizeAuthoritativeAudit(audit: AuthoritativeAudit): string[] {
  const state = audit.version_status === 'published' && audit.runtime_eligible
    ? '已发布，可运行'
    : `${audit.version_status}，不可运行`;
  return [
    state,
    `${audit.pages.total} 页（${audit.pages.indexable} 页可检索，${audit.pages.archived_non_retrieval} 页归档，${audit.pages.needs_review} 页待审）`,
    `审计门禁：${audit.gate.status}`,
  ];
}

const page: React.CSSProperties = {
  minHeight: '100vh',
  padding: 20,
  background: '#0a0a0a',
  color: '#ddd',
  fontFamily: 'sans-serif',
};

const header: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 16,
  maxWidth: 1040,
  margin: '0 auto 20px',
};

const title: React.CSSProperties = { margin: 0, fontSize: 24, color: '#8c9eff' };
const subtitle: React.CSSProperties = { marginTop: 6, color: '#777', fontSize: 13 };
const backLink: React.CSSProperties = { color: '#888', fontSize: 13 };

const section: React.CSSProperties = {
  maxWidth: 1040,
  margin: '0 auto 16px',
  padding: 16,
  border: '1px solid #222',
  borderRadius: 8,
  background: '#111',
};

const sectionTitle: React.CSSProperties = { margin: '0 0 12px', fontSize: 16, color: '#eee' };
const muted: React.CSSProperties = { color: '#666', fontSize: 13 };

const docGrid: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
  gap: 12,
};

const docCard: React.CSSProperties = {
  padding: 12,
  border: '1px solid #262626',
  borderRadius: 8,
  background: '#0d0d0d',
};

const docTitle: React.CSSProperties = { color: '#fff', fontSize: 14, fontWeight: 700 };
const docMeta: React.CSSProperties = { color: '#777', fontSize: 12, marginTop: 4 };
const docStats: React.CSSProperties = {
  display: 'flex',
  gap: 12,
  marginTop: 10,
  color: '#8c9eff',
  fontSize: 12,
};

const sampleRow: React.CSSProperties = { display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 };
const sampleButton: React.CSSProperties = {
  padding: '7px 10px',
  border: '1px solid #333',
  borderRadius: 999,
  background: '#181818',
  color: '#bbb',
  cursor: 'pointer',
  fontSize: 12,
};

const searchRow: React.CSSProperties = { display: 'flex', gap: 8 };
const input: React.CSSProperties = {
  flex: 1,
  minWidth: 0,
  padding: '10px 12px',
  borderRadius: 8,
  border: '1px solid #333',
  background: '#090909',
  color: '#eee',
  fontSize: 14,
};

const primaryButton: React.CSSProperties = {
  padding: '10px 16px',
  border: 'none',
  borderRadius: 8,
  background: '#3f51b5',
  color: '#fff',
  cursor: 'pointer',
  fontWeight: 700,
};

const errorText: React.CSSProperties = { color: '#ef9a9a', fontSize: 13, marginTop: 10 };

const resultCard: React.CSSProperties = {
  padding: 12,
  border: '1px solid #252525',
  borderRadius: 8,
  background: '#0b0b0b',
};

const resultHead: React.CSSProperties = {
  display: 'flex',
  flexWrap: 'wrap',
  gap: 10,
  color: '#8c9eff',
  fontSize: 12,
  marginBottom: 8,
};

const snippet: React.CSSProperties = {
  margin: 0,
  color: '#ccc',
  fontSize: 13,
  lineHeight: 1.7,
  whiteSpace: 'pre-wrap',
};
