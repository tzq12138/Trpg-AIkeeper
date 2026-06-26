import { useEffect, useState } from 'react';

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
  metadata?: { title?: string; index?: number; total?: number } | string;
  similarity?: number;
};

const SAMPLE_QUERIES = [
  '困难成功和极难成功怎么判定',
  '理智检定失败会怎样',
  '幸运值如何回复',
  '技能检定常规困难极难',
  '孤注一掷失败会发生什么',
];

async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...opts,
    headers: { 'Content-Type': 'application/json', ...opts?.headers },
  });
  if (!res.ok) {
    throw new Error(`${res.status}`);
  }
  return res.json();
}

export default function RagTestPage() {
  const [docs, setDocs] = useState<RuleDoc[]>([]);
  const [query, setQuery] = useState(SAMPLE_QUERIES[0]);
  const [results, setResults] = useState<RagResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const loadDocs = async () => {
    try {
      setDocs(await api<RuleDoc[]>('/api/rag/rule-docs'));
    } catch {
      setError('无法读取规则书列表，请确认后端已启动。');
    }
  };

  useEffect(() => {
    loadDocs();
  }, []);

  const search = async (nextQuery = query) => {
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
    } catch {
      setError('检索失败，请确认 RAG 后端可用。');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={page}>
      <header style={header}>
        <div>
          <h1 style={title}>规则书 RAG 测试台</h1>
          <div style={subtitle}>用于验证 COC 规则书导入后的检索命中效果</div>
        </div>
        <a href="/" style={backLink}>返回首页</a>
      </header>

      <section style={section}>
        <h2 style={sectionTitle}>已导入规则书</h2>
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
            <button key={sample} onClick={() => search(sample)} style={sampleButton}>
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
                    <span>chunk {metadata.index ?? '-'} / {metadata.total ?? '-'}</span>
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
