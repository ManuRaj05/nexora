import { NavLink, Outlet } from 'react-router-dom'
import { useCart } from '../../features/cart/CartContext.jsx'

const links = [
  { to: '/', label: 'Shop', end: true },
  { to: '/orders', label: 'Orders' },
]

export default function SiteLayout() {
  const { itemCount } = useCart()

  return (
    <div className="site-shell">
      <div className="announcement">A little more considered. A lot more everyday.</div>
      <header className="site-header">
        <div className="header-inner">
          <NavLink className="brand" to="/" aria-label="Nexora home">
            <span className="brand-mark" aria-hidden="true">n</span>
            <span>nexora<span className="brand-period">.</span></span>
          </NavLink>

          <nav className="main-nav" aria-label="Main navigation">
            {links.map(({ to, label, end }) => (
              <NavLink key={to} to={to} end={end} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="header-actions">
            <NavLink className="account-link" to="/login">Sign in</NavLink>
            <NavLink className="cart-link" to="/cart" aria-label={`Cart, ${itemCount} ${itemCount === 1 ? 'item' : 'items'}`}>
              <span className="cart-label">Cart</span>
              <span className="cart-count" aria-hidden="true">{itemCount}</span>
            </NavLink>
          </div>
        </div>
      </header>
      <main id="main-content" className="main-content">
        <Outlet />
      </main>
      <footer className="site-footer">
        <span>Made for the everyday.</span>
        <span>© {new Date().getFullYear()} Nexora</span>
      </footer>
    </div>
  )
}
