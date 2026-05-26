import EventRow from './EventRow';

export default function ActivityPanel({ events }) {
  return (
    <aside className="activity">
      <div className="activity-header">
        <h2>运行事件</h2>
        <span>{events.length}</span>
      </div>
      <div className="event-list">
        {events.length === 0 ? (
          <p className="empty">还没有事件。</p>
        ) : (
          events.map((event, index) => (
            <EventRow event={event} key={`${event.created_at || index}-${index}`} />
          ))
        )}
      </div>
    </aside>
  );
}
