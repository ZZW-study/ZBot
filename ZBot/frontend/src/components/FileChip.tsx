/**
 * FileChip — single attached file indicator. Shows filename, size, and a
 * remove button. Renders in three states: uploading (spinner), error (red),
 * or ready.
 */

import type { AttachedFile } from '../types';

interface FileChipProps {
  attached: AttachedFile;
  onRemove: () => void;
}

export default function FileChip({ attached, onRemove }: FileChipProps) {
  const { file, uploading, error, fileId } = attached;
  const sizeKb = (file.size / 1024).toFixed(1);
  return (
    <div className={`file-chip ${error ? 'is-error' : ''} ${uploading ? 'is-uploading' : ''}`}>
      <span className="file-chip-icon" aria-hidden="true">📎</span>
      <span className="file-chip-name" title={file.name}>{file.name}</span>
      <span className="file-chip-size">{sizeKb} KB</span>
      {uploading && <span className="spinner" aria-label="Uploading" />}
      {error && <span className="file-chip-error" title={error}>!</span>}
      {fileId && !uploading && !error && <span className="file-chip-ok" aria-label="Uploaded">✓</span>}
      <button
        type="button"
        className="file-chip-remove"
        aria-label={`Remove attached file ${file.name}`}
        onClick={onRemove}
        disabled={uploading}
      >
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
          <path d="M3 3l6 6M9 3l-6 6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" fill="none" />
        </svg>
      </button>
    </div>
  );
}