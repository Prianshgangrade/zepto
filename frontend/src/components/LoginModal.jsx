import React, { useState } from 'react';

export default function LoginModal({ isOpen, onClose, onLogin, error }) {
  const [username, setUsername] = useState('aarav');
  const [pin, setPin] = useState('1234');
  const [submitting, setSubmitting] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onLogin(username, pin);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-header" style={{ marginBottom: 0 }}>
          <h2>Sign in to Zepto</h2>
          <button className="close-btn" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="hint-box">
          Demo shopper accounts (verified by API Gateway Token Auth):<br />
          • <strong>aarav</strong> / PIN <code>1234</code><br />
          • <strong>priya</strong> / PIN <code>5678</code>
        </div>

        {error && <div className="banner banner-error">{error}</div>}

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div className="field-group">
            <label>Username</label>
            <input value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div className="field-group">
            <label>PIN</label>
            <input type="password" value={pin} onChange={(e) => setPin(e.target.value)} required />
          </div>
          <button className="primary-btn" type="submit" disabled={submitting}>
            {submitting ? 'Signing in...' : 'Get Access Token'}
          </button>
        </form>
      </div>
    </div>
  );
}
