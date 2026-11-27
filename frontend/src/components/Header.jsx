import React from 'react';

export default function Header({
  search,
  onSearchChange,
  activeView,
  onChangeView,
  user,
  onOpenLogin,
  onLogout,
  cartCount,
  cartTotalInr,
  onOpenCart,
  unreadNotifications,
  onOpenNotifications,
}) {
  return (
    <header className="app-header">
      <div className="brand-wrap">
        <span className="brand-logo">zepto</span>
        <span className="eta-pill">⚡ Delivery in 10 mins</span>
      </div>

      <input
        className="search-input"
        type="search"
        placeholder="Search milk, mangoes, bread, rice..."
        value={search}
        onChange={(e) => onSearchChange(e.target.value)}
      />

      <div className="header-actions">
        <button
          className={`nav-btn ${activeView === 'catalogues' ? 'active' : ''}`}
          onClick={() => onChangeView('catalogues')}
        >
          Catalogues
        </button>
        <button
          className={`nav-btn ${activeView === 'orders' ? 'active' : ''}`}
          onClick={() => onChangeView('orders')}
        >
          Orders
        </button>
        <button className="nav-btn" onClick={onOpenNotifications}>
          Notifications
          {unreadNotifications > 0 && (
            <span className="badge-count">{unreadNotifications}</span>
          )}
        </button>

        {user ? (
          <button className="nav-btn" onClick={onLogout} title="Sign out">
            {user.name.split(' ')[0]} · Sign Out
          </button>
        ) : (
          <button className="nav-btn" onClick={onOpenLogin}>
            Sign In
          </button>
        )}

        <button className="cart-btn" onClick={onOpenCart}>
          Cart ({cartCount}) · ₹{cartTotalInr.toFixed(0)}
        </button>
      </div>
    </header>
  );
}
