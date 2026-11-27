import React from 'react';

export default function CataloguesView({
  products,
  categories,
  selectedCategory,
  onSelectCategory,
  cartItemsMap,
  onAddToCart,
  onUpdateQty,
  loading,
}) {
  const allCategories = ['All', ...categories];

  return (
    <section>
      <div className="category-tabs">
        {allCategories.map((cat) => (
          <button
            key={cat}
            className={`cat-chip ${selectedCategory === cat ? 'active' : ''}`}
            onClick={() => onSelectCategory(cat)}
          >
            {cat}
          </button>
        ))}
      </div>

      {loading && products.length === 0 ? (
        <p>Loading Zepto dark-store catalogue...</p>
      ) : products.length === 0 ? (
        <p>No matching groceries found.</p>
      ) : (
        <div className="product-grid">
          {products.map((item) => {
            const inCartQty = cartItemsMap.get(item.product_id) || 0;
            const pricing = item.pricing;
            const fulfillment = item.fulfillment;

            return (
              <article key={item.product_id} className="product-card">
                <div>
                  <div className="product-visual">
                    <span>{item.image_emoji}</span>
                    {pricing.discount_percent > 0 && (
                      <span className="discount-tag">{pricing.discount_percent}% OFF</span>
                    )}
                    <span className="eta-tag">⚡ {fulfillment.promise}</span>
                  </div>
                  <div style={{ marginTop: 10 }}>
                    <div className="product-title">{item.name}</div>
                    <div className="product-meta">
                      <span>{item.unit_label}</span>
                      <span>{item.stock_qty} in stock</span>
                    </div>
                  </div>
                </div>

                <div className="product-footer">
                  <div className="price-block">
                    <span className="price-now">₹{pricing.selling_inr.toFixed(0)}</span>
                    {pricing.mrp_inr > pricing.selling_inr && (
                      <span className="price-mrp">₹{pricing.mrp_inr.toFixed(0)}</span>
                    )}
                  </div>

                  {inCartQty > 0 ? (
                    <div className="stepper">
                      <button onClick={() => onUpdateQty(item.product_id, inCartQty - 1)}>
                        −
                      </button>
                      <span>{inCartQty}</span>
                      <button
                        disabled={inCartQty >= item.stock_qty}
                        onClick={() => onUpdateQty(item.product_id, inCartQty + 1)}
                      >
                        +
                      </button>
                    </div>
                  ) : (
                    <button
                      className="add-btn"
                      disabled={!item.in_stock}
                      onClick={() => onAddToCart(item.product_id)}
                    >
                      {item.in_stock ? 'ADD' : 'OUT'}
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
