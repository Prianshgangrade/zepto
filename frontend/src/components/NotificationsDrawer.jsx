import React from 'react';

export default function NotificationsDrawer({
  isOpen,
  onClose,
  notifications,
  degraded,
  degradedReason,
  onMarkRead,
  onMarkAllRead,
}) {
  if (!isOpen) return null;

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <h2>Notifications</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            {notifications.some((n) => !n.is_read) && (
              <button className="secondary-btn" onClick={onMarkAllRead}>
                Mark all read
              </button>
            )}
            <button className="close-btn" onClick={onClose}>
              ✕
            </button>
          </div>
        </div>

        {degraded && (
          <div className="banner banner-degraded">{degradedReason}</div>
        )}

        {notifications.length === 0 ? (
          <p style={{ color: '#6b5e7a' }}>
            No notifications yet. Order & payment events arrive asynchronously here.
          </p>
        ) : (
          notifications.map((n) => (
            <div key={n.notification_id} className={`notif-card ${n.is_read ? '' : 'notif-unread'}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <strong>{n.title}</strong>
                <span style={{ fontSize: '0.72rem', color: '#6b5e7a' }}>{n.event_type}</span>
              </div>
              <p style={{ margin: '6px 0', fontSize: '0.88rem' }}>{n.message}</p>
              {!n.is_read && (
                <button className="secondary-btn" onClick={() => onMarkRead(n.notification_id)}>
                  Mark read
                </button>
              )}
            </div>
          ))
        )}
      </aside>
    </div>
  );
}
