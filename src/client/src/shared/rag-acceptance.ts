export type GoldenRagQuestion = {
  id: string;
  query: string;
  expected: string;
  expectedTerms: string[];
};

export type RAGEvidence = {
  content: string;
  metadata?: { title?: string; index?: number; page?: number } | string;
};

export const RAG_GOLDEN_QUESTIONS: GoldenRagQuestion[] = [
  { id: 'success-levels', query: '困难成功和极难成功怎么判定', expected: '命中成功等级与技能阈值规则', expectedTerms: ['困难', '极难', '常规'] },
  { id: 'sanity', query: '理智检定失败会怎样', expected: '命中理智损失或理智检定后果', expectedTerms: ['理智', 'SAN', '损失'] },
  { id: 'luck', query: '幸运值如何回复', expected: '命中幸运值恢复规则或明确限制', expectedTerms: ['幸运', '恢复', '回复'] },
  { id: 'pushed-roll', query: '孤注一掷失败会发生什么', expected: '命中孤注一掷的风险与后果', expectedTerms: ['孤注', '一掷', '后果'] },
];

function parseMetadata(metadata: RAGEvidence['metadata']): { title?: string; index?: number; page?: number } {
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

export function evaluateGoldenRagQuestion(question: GoldenRagQuestion, results: RAGEvidence[]) {
  const haystack = results.map((result) => result.content).join('\n');
  const citationFound = results.some((result) => {
    const metadata = parseMetadata(result.metadata);
    return Boolean(metadata.title) && (typeof metadata.index === 'number' || typeof metadata.page === 'number');
  });
  const relevant = question.expectedTerms.some((term) => haystack.includes(term));
  return {
    question_id: question.id,
    passed: results.length > 0 && citationFound && relevant,
    citation_found: citationFound,
    result_count: results.length,
  };
}
