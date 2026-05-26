export default function StatusRow({ label, value, tone = 'neutral' }) {
  return (
    <div className="status-row">
      <span>{label}</span>
      <strong className={`tone ${tone}`}>{value}</strong>
    </div>
  );
}
