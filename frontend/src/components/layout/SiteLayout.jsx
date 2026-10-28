import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { useCart } from '../../features/cart/CartContext.jsx'
import { useAuth } from '../../features/auth/AuthContext.jsx'

const links = [
  { to: '/', label: 'Shop', end: true },
  { to: '/orders', label: 'Orders' },
]

export default function SiteLayout() {
  const { itemCount } = useCart()
  const { user, status, isAuthenticated, logout } = useAuth()
  const navigationLinks = user?.role === 'ADMIN'
    ? [...links, { to: '/admin/products', label: 'Manage products' }]
    : links
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/', { replace: true })
  }

  return (
    <div className="site-shell">
      <div className="announcement">A little more considered. A lot more everyday. ✨</div>
      <header className="site-header">
        <div className={`header-inner${user?.role === 'ADMIN' ? ' admin-header' : ''}`}>
          <NavLink className="brand" to="/" aria-label="Nexora home">
            <span className="brand-mark" aria-hidden="true">n</span>
            <span>nexora<span className="brand-period">.</span></span>
          </NavLink>

          <nav className="main-nav" aria-label="Main navigation">
            {navigationLinks.map(({ to, label, end }) => (
              <NavLink key={to} to={to} end={end} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
                {label}
              </NavLink>
            ))}
          </nav>

          <div className="header-actions">
            {status === 'loading' ? (
              <span className="account-status" role="status">Checking…</span>
            ) : isAuthenticated ? (
              <>
                <span className="account-identity">
                  <span className="account-status">{user?.username || 'Account'}</span>
                  {user?.role === 'ADMIN' && <span className="admin-badge">ADMIN</span>}
                </span>
                <button className="account-link logout-button" type="button" onClick={handleLogout}>Sign out</button>
              </>
            ) : (
              <>
                <NavLink className="account-link" to="/login">Sign in</NavLink>
                <NavLink className="account-link register-header-link" to="/register">Join</NavLink>
              </>
            )}
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
