import { eventMessage, eventTitle, formatTime } from '../utils/format';

export default function EventRow({ event }) {
  return (
    <article className={`event-row ${event.type?.replace('.', '-') || ''}`}>
      <div>
        <strong>{eventTitle(event)}</strong>
        <time>{formatTime(event.created_at)}</time>
      </div>
      <p>{eventMessage(event)}</p>
    </article>
  );
}
