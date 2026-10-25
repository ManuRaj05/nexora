import { Link } from 'react-router-dom'

export default function OrdersPage() {
  return (
    <section className="page-panel">
      <p className="eyebrow">YOUR NEXORA STORY</p>
      <h1>Good things,<br /><em>on their way.</em></h1>
      <p className="page-description">Order history will be available in a later phase.</p>
      <div className="placeholder-notice" role="status">Sign in to find your orders here.</div>
      <Link className="text-link" to="/login">Go to sign in <span aria-hidden="true">↗</span></Link>
    </section>
  )
}
