import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCart } from '../features/cart/CartContext.jsx'
import { useAuth } from '../features/auth/AuthContext.jsx'

const formatPrice = (price) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(price)
const CHECKOUT_ATTEMPT_STORAGE_KEY = 'nexora-checkout-attempt'

function readCheckoutAttempt() {
  try {
    const attempt = JSON.parse(window.sessionStorage.getItem(CHECKOUT_ATTEMPT_STORAGE_KEY))
    if (typeof attempt?.payload !== 'string' || typeof attempt?.key !== 'string') return null

    const payload = JSON.parse(attempt.payload)
    const userId = payload?.user_id
    if (
      !Number.isInteger(userId)
      || !Array.isArray(payload?.items)
      || (attempt.userId != null && attempt.userId !== userId)
    ) return null

    return { ...attempt, userId }
  } catch {
    return null
  }
}

function saveCheckoutAttempt(attempt) {
  try {
    window.sessionStorage.setItem(CHECKOUT_ATTEMPT_STORAGE_KEY, JSON.stringify(attempt))
  } catch {
    // Keep the attempt available in memory if browser storage is unavailable.
  }
}

function clearCheckoutAttempt() {
  try {
    window.sessionStorage.removeItem(CHECKOUT_ATTEMPT_STORAGE_KEY)
  } catch {
    // The in-memory attempt is cleared by the caller.
  }
}

function createIdempotencyKey() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID()

  if (!window.crypto?.getRandomValues) {
    throw new Error('Secure checkout keys are unavailable in this browser.')
  }

  const bytes = window.crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 0x0f) | 0x40
  bytes[8] = (bytes[8] & 0x3f) | 0x80
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

export default function CartPage() {
  const { items, setQuantity, removeItem, clearCart } = useCart()
  const { user, status, isAuthenticated, authenticatedRequest } = useAuth()
  const total = items.reduce((sum, item) => sum + item.price * item.quantity, 0)
  const [submitting, setSubmitting] = useState(false)
  const [checkoutError, setCheckoutError] = useState('')
  const [signInRequired, setSignInRequired] = useState(false)
  const [createdOrder, setCreatedOrder] = useState(null)
  const checkoutAttempt = useRef(readCheckoutAttempt())
  const orderPayload = {
    user_id: user?.user_id,
    items: items.map((item) => ({ product_id: item.id, quantity: item.quantity })),
  }
  const checkoutPayload = JSON.stringify(orderPayload)

  async function handleCheckout() {
    if (submitting || !items.length) return
    if (!isAuthenticated || !user?.user_id) {
      setSignInRequired(true)
      return
    }

    setSubmitting(true)
    setCheckoutError('')
    setSignInRequired(false)
    try {
      let attempt = checkoutAttempt.current
      if (!attempt || attempt.userId !== user.user_id || attempt.payload !== checkoutPayload) {
        attempt = { userId: user.user_id, payload: checkoutPayload, key: createIdempotencyKey() }
        checkoutAttempt.current = attempt
        saveCheckoutAttempt(attempt)
      }

      const order = await authenticatedRequest('/orders', {
        method: 'POST',
        headers: { 'Idempotency-Key': attempt.key },
        body: checkoutPayload,
      })

      if (order?.id == null) {
        throw new Error('The order response did not include an order ID.')
      }

      clearCart()
      checkoutAttempt.current = null
      clearCheckoutAttempt()
      setCreatedOrder(order)
    } catch (error) {
      const ambiguous = !error.status || error.status >= 500 || error.status === 408 || (
        error.status === 409 && /already in progress/i.test(error.message)
      )
      if (!ambiguous) {
        checkoutAttempt.current = null
        clearCheckoutAttempt()
      }

      if (error.status === 401) {
        setSignInRequired(true)
        setCheckoutError('Your session is no longer valid. Please sign in again.')
      } else if (!error.status || error.status >= 500 || error.status === 408) {
        setCheckoutError('We could not confirm whether your order was created. Check Order History before retrying. Your cart has been kept.')
      } else {
        setCheckoutError(error.message || 'Your order could not be placed. Your cart has been kept.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  const signInLink = <Link to="/login" state={{ from: { pathname: '/cart' } }}>Sign in</Link>

  return (
    <section className="page-panel">
      <p className="eyebrow">YOUR SELECTION</p>
      <h1>{createdOrder ? <>Order placed,<br /><em>good things ahead.</em></> : items.length ? <>Good things,<br /><em>gathered here.</em></> : <>A little space<br />for <em>good things.</em></>}</h1>
      {createdOrder ? (
        <div className="form-message form-success" role="status">
          <p>Order #{createdOrder.id} was created successfully.</p>
          <Link className="text-link" to="/orders">View Order History <span aria-hidden="true">↗</span></Link>
        </div>
      ) : !items.length ? (
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
                  <input aria-label={`Quantity for ${item.name}`} type="number" min="1" max={item.stock} value={item.quantity} disabled={submitting} onChange={(event) => setQuantity(item.id, event.target.value)} />
                </label>
                <strong className="cart-line-total">{formatPrice(item.price * item.quantity)}</strong>
                <button className="remove-button" type="button" onClick={() => removeItem(item.id)} aria-label={`Remove ${item.name} from cart`} disabled={submitting}>×</button>
              </article>
            ))}
          </div>
          <div className="cart-summary"><span>Subtotal</span><strong>{formatPrice(total)}</strong></div>
          <p className="cart-note">Prices and stock are checked again when you place your order.</p>
          {status === 'loading' && <p className="form-message" role="status">Checking your sign-in…</p>}
          {(status === 'anonymous' || signInRequired) && !checkoutError && (
            <div className="form-message form-error" role="status">Sign-in is required to place an order. {signInLink}</div>
          )}
          {checkoutError && <div className="form-message form-error" role="alert">{checkoutError} {signInRequired && signInLink}</div>}
          <button className="button button-dark" type="button" onClick={handleCheckout} disabled={submitting || status === 'loading' || !isAuthenticated}>
            {submitting ? 'Placing order…' : status === 'loading' ? 'Checking sign-in…' : 'Checkout'} <span aria-hidden="true">↗</span>
          </button>
          <Link className="text-link" to="/">Continue exploring <span aria-hidden="true">↗</span></Link>
        </>
      )}
    </section>
  )
}
