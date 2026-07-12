import type { RedactedCitation } from '../shared/types';


export default function RedactedCitationDisclosure({ citations }: { citations: RedactedCitation[] }) {
  const safeCitations = citations
    .map((citation) => ({
      label: String(citation.label || '已校验依据'),
      page: typeof citation.page === 'number' ? citation.page : null,
      scene: citation.scene ? String(citation.scene) : '',
    }))
    .filter((citation) => citation.label || citation.page || citation.scene);

  if (safeCitations.length === 0) {
    return <p className="bh-eyebrow">依据已校验</p>;
  }

  return (
    <details className="bh-redacted-citations">
      <summary>依据已校验</summary>
      <ul>
        {safeCitations.map((citation, index) => (
          <li key={`${citation.label}-${citation.page ?? 'na'}-${index}`}>
            <span>{citation.label}</span>
            {citation.page ? <span> · 第 {citation.page} 页</span> : null}
            {citation.scene ? <span> · {citation.scene}</span> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}
