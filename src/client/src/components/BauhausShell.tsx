import type { ReactNode } from 'react';

interface BauhausPageProps {
  children: ReactNode;
  narrow?: boolean;
  className?: string;
}

export function BauhausPage({ children, narrow = false, className = '' }: BauhausPageProps) {
  return (
    <main className={`bh-page ${narrow ? 'bh-page--narrow' : ''} ${className}`}>
      {children}
    </main>
  );
}

interface BrutalProgressProps {
  label: string;
  value: number;
  max: number;
  tone?: 'yellow' | 'red';
}

export function BrutalProgress({ label, value, max, tone = 'yellow' }: BrutalProgressProps) {
  const percent = max > 0 ? Math.max(0, Math.min(100, (value / max) * 100)) : 0;
  return (
    <div className="bh-stat-bar">
      <span>{label}</span>
      <div className="bh-stat-track">
        <div
          className={`bh-stat-fill ${tone === 'red' ? 'bh-stat-fill--red' : ''}`}
          style={{ width: `${percent}%` }}
        />
        <span className="bh-stat-value">{value}/{max}</span>
      </div>
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return <span className="bh-eyebrow">{children}</span>;
}
