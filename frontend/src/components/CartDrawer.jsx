import React, { useState } from 'react';

export default function CartDrawer({
  isOpen,
  onClose,
  cart,
  user,
  onOpenLogin,
  onUpdateQty,
  onClearCart,
  onCheckout,
  checkingOut,
}) {
  const [deliveryAddress, setDeliveryAddress] = useState(
    '221B Zepto Dark Store Zone, Indiranagar, Bengaluru'
  );
  const [paymentMethod, setPaymentMethod] = useState('UPI');
  const [paymentToken, setPaymentToken] = useState('aarav@zepto');

  if (!isOpen) return null;

  const items = cart?.items || [];

  const handleSubmit = (e) => {
    e.preventDefault();
    onCheckout({ deliveryAddress, paymentMethod, paymentToken });
  };

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header">
          <h2>Your Cart ({cart?.total_items || 0})</h2>
          <button className="close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        {!user ? (
          <div style={{ marginTop: 20 }}>
            <p>Sign in with your Zero-Trust shopper token to manage your cart and place orders.</p>
            <button className="primary-btn" onClick={onOpenLogin}>
              Sign In to Shop
            </button>
          </div>
        ) : items.length === 0 ? (
          <p style={{ color: '#6b5e7a' }}>Your Zepto cart is empty. Add groceries to start!</p>
        ) : (
          <>
            {cart?.degraded && (
              <div className="banner banner-degraded">{cart.degraded_reason}</div>
            )}
            <div>
              {items.map((item) => (
                <div key={item.product_id} className="cart-item-row">
                  <div>
                    <strong>
                      {item.image_emoji} {item.name}
                    </strong>
                    <div style={{ fontSize: '0.8rem', color: '#6b5e7a' }}>
                      {item.unit_label} · ₹{item.unit_price_inr.toFixed(0)} each
                    </div>
                  </div>
                  <div className="stepper">
                    <button onClick={() => onUpdateQty(item.product_id, item.quantity - 1)}>
                      −
                    </button>
                    <span>{item.quantity}</span>
                    <button onClick={() => onUpdateQty(item.product_id, item.quantity + 1)}>
                      +
                    </button>
                  </div>
                </div>
              ))}
            </div>

            <div style={{ marginTop: 12, textAlign: 'right' }}>
              <button className="secondary-btn" onClick={onClearCart}>
                Clear Cart
              </button>
            </div>

            <form className="checkout-box" onSubmit={handleSubmit}>
              <div className="field-group">
                <label>Delivery Address</label>
                <input
                  value={deliveryAddress}
                  onChange={(e) => setDeliveryAddress(e.target.value)}
                  required
                  minLength={5}
                />
              </div>
              <div className="field-group">
                <label>Payment Method (Payments Service)</label>
                <select
                  value={paymentMethod}
                  onChange={(e) => setPaymentMethod(e.target.value)}
                >
                  <option value="UPI">UPI</option>
                  <option value="CARD">CARD</option>
                  <option value="WALLET">WALLET</option>
                </select>
              </div>
              <div className="field-group">
                <label>Payment Handle / Token (use decline@upi to test Saga rollback)</label>
                <input
                  value={paymentToken}
                  onChange={(e) => setPaymentToken(e.target.value)}
                  required
                  minLength={2}
                />
              </div>

              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  fontWeight: 800,
                  fontSize: '1.05rem',
                  marginTop: 6,
                }}
              >
                <span>To Pay</span>
                <span>₹{(cart?.total_inr || 0).toFixed(2)}</span>
              </div>

              <button className="primary-btn" type="submit" disabled={checkingOut}>
                {checkingOut ? 'Placing Order...' : `Pay ₹${(cart?.total_inr || 0).toFixed(2)} & Place Order`}
              </button>
            </form>
          </>
        )}
      </aside>
    </div>
  );
}
