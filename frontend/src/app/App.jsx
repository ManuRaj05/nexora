import { Navigate, Route, Routes } from 'react-router-dom'
import SiteLayout from '../components/layout/SiteLayout.jsx'
import HomePage from '../pages/HomePage.jsx'
import LoginPage from '../pages/LoginPage.jsx'
import RegisterPage from '../pages/RegisterPage.jsx'
import CartPage from '../pages/CartPage.jsx'
import OrdersPage from '../pages/OrdersPage.jsx'
import { CartProvider } from '../features/cart/CartContext.jsx'

export default function App() {
  return (
    <CartProvider>
      <Routes>
        <Route element={<SiteLayout />}>
          <Route index element={<HomePage />} />
          <Route path="login" element={<LoginPage />} />
          <Route path="register" element={<RegisterPage />} />
          <Route path="cart" element={<CartPage />} />
          <Route path="orders" element={<OrdersPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </CartProvider>
  )
}
