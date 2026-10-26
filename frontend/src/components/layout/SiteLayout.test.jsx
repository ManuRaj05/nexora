import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const contexts = vi.hoisted(() => ({ useAuth: vi.fn(), useCart: vi.fn() }))
vi.mock('../../features/auth/AuthContext.jsx', () => ({ useAuth: contexts.useAuth }))
vi.mock('../../features/cart/CartContext.jsx', () => ({ useCart: contexts.useCart }))

import SiteLayout from './SiteLayout.jsx'

afterEach(() => cleanup())

function renderLayout(role) {
  contexts.useAuth.mockReturnValue({
    user: { user_id: 8, username: 'shopper', role },
    status: 'authenticated',
    isAuthenticated: true,
    logout: vi.fn(),
  })
  contexts.useCart.mockReturnValue({ itemCount: 0 })
  return render(
    <MemoryRouter>
      <Routes><Route element={<SiteLayout />}><Route index element={<p>Storefront</p>} /></Route></Routes>
    </MemoryRouter>,
  )
}

describe('admin navigation visibility', () => {
  it('shows product management navigation to administrators', () => {
    renderLayout('ADMIN')
    expect(screen.getByRole('link', { name: 'Manage products' })).toBeTruthy()
  })

  it('hides product management navigation from customers', () => {
    renderLayout('CUSTOMER')
    expect(screen.queryByRole('link', { name: 'Manage products' })).toBeNull()
  })
})
