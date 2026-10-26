import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const auth = vi.hoisted(() => ({ useAuth: vi.fn() }))
vi.mock('./AuthContext.jsx', () => ({ useAuth: auth.useAuth }))

import ProtectedRoute from './ProtectedRoute.jsx'

afterEach(() => cleanup())

function renderRoleRoute(user) {
  auth.useAuth.mockReturnValue({
    user,
    status: 'authenticated',
    isAuthenticated: true,
    sessionMessage: '',
  })
  return render(
    <MemoryRouter initialEntries={['/admin/products']}>
      <Routes>
        <Route path="/" element={<p>Shop page</p>} />
        <Route path="/admin/products" element={<ProtectedRoute requiredRole="ADMIN"><p>Product admin tools</p></ProtectedRoute>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('role protected routes', () => {
  it('renders admin tools for an administrator', () => {
    renderRoleRoute({ user_id: 3, role: 'ADMIN' })
    expect(screen.getByText('Product admin tools')).toBeTruthy()
  })

  it('redirects customers away from admin tools', () => {
    renderRoleRoute({ user_id: 4, role: 'CUSTOMER' })
    expect(screen.getByText('Shop page')).toBeTruthy()
    expect(screen.queryByText('Product admin tools')).toBeNull()
  })
})
