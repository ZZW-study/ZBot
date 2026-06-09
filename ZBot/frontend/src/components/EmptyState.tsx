/**
 * EmptyState — generic empty state with optional example prompts.
 */

import type { ReactNode } from 'react';

interface EmptyStateProps {
  title: string;
  description?: string;
  icon?: ReactNode;
  cta?: ReactNode;
  examples?: { label: string; onPick: (label: string) => void }[];
}

export default function EmptyState({ title, description, icon, cta, examples }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state-icon" aria-hidden="true">{icon}</div>}
      <h3 className="empty-state-title">{title}</h3>
      {description && <p className="empty-state-description">{description}</p>}
      {cta && <div className="empty-state-cta">{cta}</div>}
      {examples && examples.length > 0 && (
        <ul className="empty-state-examples">
          {examples.map((ex) => (
            <li key={ex.label}>
              <button
                type="button"
                className="empty-state-example"
                onClick={() => ex.onPick(ex.label)}
              >
                {ex.label}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}