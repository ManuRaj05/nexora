import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const contexts = vi.hoisted(() => ({ useAuth: vi.fn(), useCart: vi.fn() }))
vi.mock('../../features/auth/AuthContext.jsx', () => ({ useAuth: contexts.useAuth }))
vi.mock('../../features/cart/CartContext.jsx', () => ({ useCart: contexts.useCart }))

import SiteLayout from './SiteLayout.jsx'

afterEach(() => cleanup())

function renderLayout(role) {
  const user = role ? { user_id: 8, username: 'shopper', role } : null
  contexts.useAuth.mockReturnValue({
    user,
    status: user ? 'authenticated' : 'anonymous',
    isAuthenticated: Boolean(user),
    logout: vi.fn(),
  })
  contexts.useCart.mockReturnValue({ itemCount: 0 })
  return render(layoutTree())
}

function layoutTree() {
  return (
    <MemoryRouter>
      <Routes><Route element={<SiteLayout />}><Route index element={<p>Storefront</p>} /></Route></Routes>
    </MemoryRouter>
  )
}

describe('admin navigation visibility', () => {
  it('shows product management navigation to administrators', () => {
    renderLayout('ADMIN')
    expect(screen.getByRole('link', { name: 'Manage products' })).toBeTruthy()
    expect(screen.getByText('ADMIN', { exact: true })).toBeTruthy()
  })

  it('hides the admin navigation and badge from customers', () => {
    renderLayout('CUSTOMER')
    expect(screen.queryByRole('link', { name: 'Manage products' })).toBeNull()
    expect(screen.queryByText('ADMIN', { exact: true })).toBeNull()
  })

  it('hides the admin badge from anonymous visitors', () => {
    renderLayout(null)
    expect(screen.queryByText('ADMIN', { exact: true })).toBeNull()
  })

  it('updates the badge when the authenticated account changes', () => {
    const view = renderLayout('ADMIN')
    expect(screen.getByText('ADMIN', { exact: true })).toBeTruthy()

    contexts.useAuth.mockReturnValue({
      user: { user_id: 9, username: 'customer', role: 'CUSTOMER' },
      status: 'authenticated',
      isAuthenticated: true,
      logout: vi.fn(),
    })
    view.rerender(layoutTree())

    expect(screen.queryByText('ADMIN', { exact: true })).toBeNull()
  })
})
