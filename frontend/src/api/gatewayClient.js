const BASE_URL = import.meta.env.VITE_GATEWAY_URL || '';

async function request(path, { method = 'GET', token = null, body = null, headers = {} } = {}) {
  const reqHeaders = { ...headers };
  if (token) {
    reqHeaders.Authorization = `Bearer ${token}`;
  }
  if (body !== null) {
    reqHeaders['Content-Type'] = 'application/json';
  }

  const resp = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: reqHeaders,
    body: body !== null ? JSON.stringify(body) : undefined,
  });

  const text = await resp.text();
  const data = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    const err = new Error(data.detail || data.failure_reason || `Request failed (${resp.status})`);
    err.status = resp.status;
    err.data = data;
    throw err;
  }
  return {
    data,
    status: resp.status,
    apiVersion: resp.headers.get('X-API-Version'),
    degraded: Boolean(data.degraded || resp.headers.get('X-Degraded') === 'true'),
  };
}

export const gatewayApi = {
  login: (username, pin) =>
    request('/api/v1/auth/token', {
      method: 'POST',
      body: { username, pin },
    }),

  listCataloguesV2: ({ category = '', search = '' } = {}) => {
    const params = new URLSearchParams();
    if (category && category !== 'All') params.set('category', category);
    if (search.trim()) params.set('search', search.trim());
    const qs = params.toString();
    return request(`/api/v2/catalogues/products${qs ? `?${qs}` : ''}`);
  },

  getCart: (token) => request('/api/v1/cart', { token }),

  addToCart: (token, productId, quantity = 1) =>
    request('/api/v1/cart/items', {
      method: 'POST',
      token,
      body: { product_id: productId, quantity },
    }),

  updateCartQty: (token, productId, quantity) =>
    request(`/api/v1/cart/items/${productId}`, {
      method: 'PATCH',
      token,
      body: { quantity },
    }),

  clearCart: (token) =>
    request('/api/v1/cart', {
      method: 'DELETE',
      token,
    }),

  placeOrder: (token, { deliveryAddress, paymentMethod, paymentToken, idempotencyKey }) =>
    request('/api/v1/orders', {
      method: 'POST',
      token,
      headers: { 'Idempotency-Key': idempotencyKey },
      body: {
        delivery_address: deliveryAddress,
        payment_method: paymentMethod,
        payment_token: paymentToken,
      },
    }),

  listOrders: (token) => request('/api/v1/orders', { token }),

  retryPayment: (token, orderId, { paymentMethod, paymentToken }) =>
    request(`/api/v1/orders/${orderId}/retry-payment`, {
      method: 'POST',
      token,
      body: { payment_method: paymentMethod, payment_token: paymentToken },
    }),

  cancelOrder: (token, orderId) =>
    request(`/api/v1/orders/${orderId}/cancel`, {
      method: 'POST',
      token,
    }),

  listNotifications: (token) => request('/api/v1/notifications', { token }),

  markNotificationRead: (token, notificationId) =>
    request(`/api/v1/notifications/${notificationId}/read`, {
      method: 'POST',
      token,
    }),

  markAllNotificationsRead: (token) =>
    request('/api/v1/notifications/read-all', {
      method: 'POST',
      token,
    }),
};
