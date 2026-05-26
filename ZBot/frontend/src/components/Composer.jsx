export default function Composer({ input, setInput, onSend, disabled }) {
  const handleKeyDown = (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      onSend();
    }
  };

  return (
    <footer className="composer">
      <textarea
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入任务，Ctrl/⌘ + Enter 发送"
        rows={3}
      />
      <button type="button" onClick={onSend} disabled={disabled}>
        发送
      </button>
    </footer>
  );
}
