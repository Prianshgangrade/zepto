import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { gatewayApi } from './api/gatewayClient.js';
import Header from './components/Header.jsx';
import CataloguesView from './components/CataloguesView.jsx';
import CartDrawer from './components/CartDrawer.jsx';
import OrdersView from './components/OrdersView.jsx';
import NotificationsDrawer from './components/NotificationsDrawer.jsx';
import LoginModal from './components/LoginModal.jsx';

const SESSION_KEY = 'zepto_auth_session';

function loadSavedSession() {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export default function App() {
  const [session, setSession] = useState(loadSavedSession);
  const [activeView, setActiveView] = useState('catalogues');
  const [search, setSearch] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('All');

  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [cataloguesDegraded, setCataloguesDegraded] = useState(null);
  const [loadingProducts, setLoadingProducts] = useState(false);

  const [cart, setCart] = useState({ total_items: 0, total_inr: 0, items: [] });
  const [cartOpen, setCartOpen] = useState(false);
  const [checkingOut, setCheckingOut] = useState(false);

  const [orders, setOrders] = useState([]);
  const [notificationsState, setNotificationsState] = useState({
    items: [],
    unread_count: 0,
    degraded: false,
    degraded_reason: null,
  });
  const [notifOpen, setNotifOpen] = useState(false);

  const [loginOpen, setLoginOpen] = useState(false);
  const [loginError, setLoginError] = useState(null);
  const [banner, setBanner] = useState(null);

  const token = session?.access_token || null;
  const user = session?.user || null;

  const loadCatalogues = useCallback(async () => {
    setLoadingProducts(true);
    try {
      const res = await gatewayApi.listCataloguesV2({
        category: selectedCategory,
        search,
      });
      setProducts(res.data.items || []);
      setCategories(res.data.categories || []);
      setCataloguesDegraded(res.degraded ? res.data.degraded_reason : null);
    } catch (err) {
      setBanner({ type: 'error', text: err.message });
    } finally {
      setLoadingProducts(false);
    }
  }, [selectedCategory, search]);

  const loadCart = useCallback(async () => {
    if (!token) {
      setCart({ total_items: 0, total_inr: 0, items: [] });
      return;
    }
    try {
      const res = await gatewayApi.getCart(token);
      setCart(res.data);
    } catch (err) {
      if (err.status === 401) {
        localStorage.removeItem(SESSION_KEY);
        setSession(null);
      }
    }
  }, [token]);

  const loadOrders = useCallback(async () => {
    if (!token) {
      setOrders([]);
      return;
    }
    try {
      const res = await gatewayApi.listOrders(token);
      setOrders(res.data.items || []);
    } catch {
      // Keep current list on transient polling errors
    }
  }, [token]);

  const loadNotifications = useCallback(async () => {
    if (!token) {
      setNotificationsState({ items: [], unread_count: 0, degraded: false, degraded_reason: null });
      return;
    }
    try {
      const res = await gatewayApi.listNotifications(token);
      setNotificationsState({
        items: res.data.items || [],
        unread_count: res.data.unread_count || 0,
        degraded: res.degraded,
        degraded_reason: res.data.degraded_reason || null,
      });
    } catch {
      // Non-blocking notification fetch
    }
  }, [token]);

  useEffect(() => {
    loadCatalogues();
  }, [loadCatalogues]);

  useEffect(() => {
    loadCart();
    loadOrders();
    loadNotifications();
  }, [loadCart, loadOrders, loadNotifications]);

  // Poll notifications & eventual consistency updates periodically when signed in
  useEffect(() => {
    if (!token) return undefined;
    const timer = setInterval(() => {
      loadNotifications();
      if (activeView === 'orders' || orders.some((o) => o.status === 'PAYMENT_PENDING')) {
        loadOrders();
      }
    }, 2500);
    return () => clearInterval(timer);
  }, [token, activeView, orders, loadNotifications, loadOrders]);

  const cartItemsMap = useMemo(() => {
    const map = new Map();
    for (const item of cart?.items || []) {
      map.set(item.product_id, item.quantity);
    }
    return map;
  }, [cart]);

  const handleLogin = async (username, pin) => {
    setLoginError(null);
    try {
      const res = await gatewayApi.login(username, pin);
      localStorage.setItem(SESSION_KEY, JSON.stringify(res.data));
      setSession(res.data);
      setLoginOpen(false);
      setBanner({ type: 'info', text: `Signed in as ${res.data.user.name}` });
    } catch (err) {
      setLoginError(err.message);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem(SESSION_KEY);
    setSession(null);
    setCart({ total_items: 0, total_inr: 0, items: [] });
    setOrders([]);
    setNotificationsState({ items: [], unread_count: 0, degraded: false, degraded_reason: null });
  };

  const handleAddToCart = async (productId) => {
    if (!token) {
      setLoginOpen(true);
      return;
    }
    try {
      const res = await gatewayApi.addToCart(token, productId, 1);
      setCart(res.data);
    } catch (err) {
      setBanner({ type: 'error', text: err.message });
    }
  };

  const handleUpdateQty = async (productId, qty) => {
    if (!token) return;
    try {
      const res = await gatewayApi.updateCartQty(token, productId, Math.max(0, qty));
      setCart(res.data);
    } catch (err) {
      setBanner({ type: 'error', text: err.message });
    }
  };

  const handleClearCart = async () => {
    if (!token) return;
    const res = await gatewayApi.clearCart(token);
    setCart(res.data);
  };

  const handleCheckout = async ({ deliveryAddress, paymentMethod, paymentToken }) => {
    if (!token) return;
    setCheckingOut(true);
    try {
      const idempotencyKey = `web-${crypto.randomUUID()}`;
      const res = await gatewayApi.placeOrder(token, {
        deliveryAddress,
        paymentMethod,
        paymentToken,
        idempotencyKey,
      });
      setCartOpen(false);
      setActiveView('orders');
      setBanner({
        type: res.degraded ? 'degraded' : res.data.status === 'PAYMENT_FAILED' ? 'error' : 'info',
        text: res.degraded
          ? res.data.degraded_reason
          : `Order ${res.data.order_id} status: ${res.data.status}`,
      });
      await Promise.all([loadCatalogues(), loadOrders()]);
      setTimeout(() => {
        loadCart();
        loadNotifications();
      }, 350);
    } catch (err) {
      setBanner({ type: 'error', text: err.message });
    } finally {
      setCheckingOut(false);
    }
  };

  const handleRetryPayment = async (orderId) => {
    if (!token) return;
    try {
      const res = await gatewayApi.retryPayment(token, orderId, {
        paymentMethod: 'UPI',
        paymentToken: 'zepto@upi',
      });
      setBanner({
        type: res.degraded ? 'degraded' : 'info',
        text: `Order ${orderId} updated: ${res.data.status}`,
      });
      await Promise.all([loadOrders(), loadNotifications(), loadCatalogues()]);
    } catch (err) {
      setBanner({ type: 'error', text: err.message });
    }
  };

  const handleCancelOrder = async (orderId) => {
    if (!token) return;
    try {
      await gatewayApi.cancelOrder(token, orderId);
      setBanner({ type: 'info', text: `Order ${orderId} cancelled. Stock released asynchronously.` });
      await loadOrders();
      setTimeout(() => {
        loadCatalogues();
        loadNotifications();
      }, 350);
    } catch (err) {
      setBanner({ type: 'error', text: err.message });
    }
  };

  const handleMarkNotificationRead = async (id) => {
    if (!token) return;
    await gatewayApi.markNotificationRead(token, id);
    loadNotifications();
  };

  const handleMarkAllNotificationsRead = async () => {
    if (!token) return;
    await gatewayApi.markAllNotificationsRead(token);
    loadNotifications();
  };

  return (
    <div>
      <Header
        search={search}
        onSearchChange={setSearch}
        activeView={activeView}
        onChangeView={setActiveView}
        user={user}
        onOpenLogin={() => setLoginOpen(true)}
        onLogout={handleLogout}
        cartCount={cart?.total_items || 0}
        cartTotalInr={cart?.total_inr || 0}
        onOpenCart={() => setCartOpen(true)}
        unreadNotifications={notificationsState.unread_count}
        onOpenNotifications={() => {
          if (!token) setLoginOpen(true);
          else {
            loadNotifications();
            setNotifOpen(true);
          }
        }}
      />

      <main className="main-container">
        {cataloguesDegraded && (
          <div className="banner banner-degraded">{cataloguesDegraded}</div>
        )}

        {banner && (
          <div className={`banner banner-${banner.type}`}>
            <span>{banner.text}</span>
            <button className="close-btn" onClick={() => setBanner(null)}>
              ✕
            </button>
          </div>
        )}

        {activeView === 'catalogues' ? (
          <CataloguesView
            products={products}
            categories={categories}
            selectedCategory={selectedCategory}
            onSelectCategory={setSelectedCategory}
            cartItemsMap={cartItemsMap}
            onAddToCart={handleAddToCart}
            onUpdateQty={handleUpdateQty}
            loading={loadingProducts}
          />
        ) : (
          <OrdersView
            orders={orders}
            user={user}
            onOpenLogin={() => setLoginOpen(true)}
            onRetryPayment={handleRetryPayment}
            onCancelOrder={handleCancelOrder}
            onRefresh={loadOrders}
          />
        )}
      </main>

      <CartDrawer
        isOpen={cartOpen}
        onClose={() => setCartOpen(false)}
        cart={cart}
        user={user}
        onOpenLogin={() => {
          setCartOpen(false);
          setLoginOpen(true);
        }}
        onUpdateQty={handleUpdateQty}
        onClearCart={handleClearCart}
        onCheckout={handleCheckout}
        checkingOut={checkingOut}
      />

      <NotificationsDrawer
        isOpen={notifOpen}
        onClose={() => setNotifOpen(false)}
        notifications={notificationsState.items}
        degraded={notificationsState.degraded}
        degradedReason={notificationsState.degraded_reason}
        onMarkRead={handleMarkNotificationRead}
        onMarkAllRead={handleMarkAllNotificationsRead}
      />

      <LoginModal
        isOpen={loginOpen}
        onClose={() => setLoginOpen(false)}
        onLogin={handleLogin}
        error={loginError}
      />
    </div>
  );
}
