import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../features/auth/AuthContext.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import LoadingState from '../components/ui/LoadingState.jsx'

function formatCurrency(value) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return 'Total unavailable'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(Number(value))
}

function formatDate(value) {
  if (!value) return 'Date unavailable'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export default function OrdersPage() {
  const { authenticatedRequest } = useAuth()
  const [orders, setOrders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reloadCount, setReloadCount] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')

    authenticatedRequest('/orders', { signal: controller.signal })
      .then((result) => {
        if (!Array.isArray(result)) throw new Error('The order history response was not a list.')
        setOrders(result)
      })
      .catch((requestError) => {
        if (requestError.name !== 'AbortError') {
          setError(requestError.message || 'Could not load your order history.')
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false)
      })

    return () => controller.abort()
  }, [authenticatedRequest, reloadCount])

  return (
    <section className="page-panel">
      <p className="eyebrow">YOUR NEXORA STORY</p>
      <h1>Your orders,<br /><em>all in one place.</em></h1>
      <p className="page-description">A little record of the good things you’ve chosen.</p>
      {loading && <LoadingState label="Loading your order history…" />}
      {error && (
        <>
          <ErrorState title="Your orders are taking a moment" message={error} />
          <button className="text-link retry-button" type="button" onClick={() => setReloadCount((count) => count + 1)}>Try again <span aria-hidden="true">↻</span></button>
        </>
      )}
      {!loading && !error && orders.length === 0 && (
        <>
          <div className="placeholder-notice" role="status">No orders yet. Your next favourite is waiting to be found.</div>
          <Link className="text-link" to="/">Back to shopping <span aria-hidden="true">↗</span></Link>
        </>
      )}
      {!loading && !error && orders.length > 0 && (
        <>
          <div className="order-list">
            {orders.map((order, orderIndex) => (
              <article className="placeholder-notice" key={order.id ?? orderIndex}>
                <h2>Order #{order.id ?? '—'}</h2>
                <p>Status: {order.status || 'Status unavailable'}</p>
                <p>Total: {formatCurrency(order.total_amount)}</p>
                <p>Placed: {formatDate(order.created_at)}</p>
                {Array.isArray(order.items) && order.items.length > 0 ? (
                  <ul>
                    {order.items.map((item, itemIndex) => (
                      <li key={`${order.id ?? orderIndex}-${item.product_id ?? itemIndex}`}>
                        Product #{item.product_id ?? '—'} · Quantity {item.quantity ?? 'unavailable'}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>Order items unavailable.</p>
                )}
              </article>
            ))}
          </div>
          <Link className="text-link" to="/">Back to shopping <span aria-hidden="true">↗</span></Link>
        </>
      )}
    </section>
  )
}
