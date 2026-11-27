import React from 'react';

export default function OrdersView({ orders, user, onOpenLogin, onRetryPayment, onCancelOrder, onRefresh }) {
  if (!user) {
    return (
      <div className="order-card">
        <h3>Sign in to view your Orders</h3>
        <button className="primary-btn" onClick={onOpenLogin}>
          Sign In
        </button>
      </div>
    );
  }

  return (
    <section>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
        <h2 style={{ margin: 0 }}>Your Orders</h2>
        <button className="secondary-btn" onClick={onRefresh}>
          Refresh Orders
        </button>
      </div>

      {orders.length === 0 ? (
        <div className="order-card">No orders placed yet.</div>
      ) : (
        orders.map((order) => (
          <article key={order.order_id} className="order-card">
            <div className="order-top">
              <div>
                <strong>{order.order_id}</strong>
                <div style={{ fontSize: '0.82rem', color: '#6b5e7a' }}>
                  {order.delivery_address} · {order.payment_method}
                </div>
              </div>
              <span className={`status-badge status-${order.status}`}>{order.status}</span>
            </div>

            {order.failure_reason && (
              <div className="banner banner-error" style={{ marginBottom: 10 }}>
                {order.failure_reason}
              </div>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12 }}>
              {order.items.map((item) => (
                <div key={item.product_id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.9rem' }}>
                  <span>
                    {item.image_emoji} {item.name} × {item.quantity}
                  </span>
                  <span>₹{(item.line_total_paise / 100).toFixed(2)}</span>
                </div>
              ))}
            </div>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <strong>Total: ₹{order.total_inr.toFixed(2)}</strong>
              <div style={{ display: 'flex', gap: 8 }}>
                {order.status === 'PAYMENT_PENDING' && (
                  <button className="secondary-btn" onClick={() => onRetryPayment(order.order_id)}>
                    Retry Payment
                  </button>
                )}
                {(order.status === 'PAYMENT_PENDING' || order.status === 'CONFIRMED') && (
                  <button className="secondary-btn" onClick={() => onCancelOrder(order.order_id)}>
                    Cancel Order
                  </button>
                )}
              </div>
            </div>
          </article>
        ))
      )}
    </section>
  );
}
