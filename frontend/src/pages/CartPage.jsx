import { Link } from 'react-router-dom'
import { useCart } from '../features/cart/CartContext.jsx'

const formatPrice = (price) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(price)

export default function CartPage() {
  const { items, setQuantity, removeItem } = useCart()
  const total = items.reduce((sum, item) => sum + item.price * item.quantity, 0)

  return (
    <section className="page-panel">
      <p className="eyebrow">YOUR SELECTION</p>
      <h1>{items.length ? <>Good things,<br /><em>gathered here.</em></> : <>A little space<br />for <em>good things.</em></>}</h1>
      {!items.length ? (
        <>
          <p className="page-description">Your cart is waiting to be filled.</p>
          <Link className="text-link" to="/">Back to the collection <span aria-hidden="true">↗</span></Link>
        </>
      ) : (
        <>
          <p className="page-description">{items.reduce((sum, item) => sum + item.quantity, 0)} items in your selection. Checkout will be available in a later phase.</p>
          <div className="cart-list">
            {items.map((item) => (
              <article className="cart-row" key={item.id}>
                <div className={`cart-thumb visual-${Math.abs(Number(item.id) || 0) % 4}`} aria-hidden="true"><span className="visual-shape" /></div>
                <div className="cart-item-info"><p className="product-category">{item.category || 'NEXORA FIND'}</p><h2>{item.name}</h2><span>{formatPrice(item.price)} each</span></div>
                <label className="quantity-control">Quantity
                  <input aria-label={`Quantity for ${item.name}`} type="number" min="1" max={item.stock} value={item.quantity} onChange={(event) => setQuantity(item.id, event.target.value)} />
                </label>
                <strong className="cart-line-total">{formatPrice(item.price * item.quantity)}</strong>
                <button className="remove-button" type="button" onClick={() => removeItem(item.id)} aria-label={`Remove ${item.name} from cart`}>×</button>
              </article>
            ))}
          </div>
          <div className="cart-summary"><span>Subtotal</span><strong>{formatPrice(total)}</strong></div>
          <p className="cart-note">Order placement will be added in a later phase.</p>
          <Link className="text-link" to="/">Continue exploring <span aria-hidden="true">↗</span></Link>
        </>
      )}
    </section>
  )
}
