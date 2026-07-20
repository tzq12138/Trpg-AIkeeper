import { describe, expect, it } from 'vitest';
import { evaluateGoldenRagQuestion, RAG_GOLDEN_QUESTIONS } from '../src/shared/rag-acceptance';

describe('evaluateGoldenRagQuestion', () => {
  it('passes only when a relevant result has an auditable citation', () => {
    const result = evaluateGoldenRagQuestion(RAG_GOLDEN_QUESTIONS[0], [
      { content: '常规、困难和极难成功分别按技能值的一半与五分之一判断。', metadata: { title: 'CoC7 基础规则', index: 12 } },
    ]);

    expect(result.passed).toBe(true);
    expect(result.citation_found).toBe(true);
  });

  it('fails a result that has no citation even when content looks relevant', () => {
    const result = evaluateGoldenRagQuestion(RAG_GOLDEN_QUESTIONS[0], [
      { content: '困难与极难成功的判定见规则。', metadata: {} },
    ]);

    expect(result.passed).toBe(false);
    expect(result.citation_found).toBe(false);
  });
});
