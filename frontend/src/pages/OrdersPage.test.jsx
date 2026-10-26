import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'

const auth = vi.hoisted(() => ({ authenticatedRequest: vi.fn() }))
vi.mock('../features/auth/AuthContext.jsx', () => ({
  useAuth: () => ({ authenticatedRequest: auth.authenticatedRequest }),
}))

import OrdersPage from './OrdersPage.jsx'

afterEach(() => cleanup())

beforeEach(() => {
  vi.clearAllMocks()
})

function renderOrders(orders) {
  auth.authenticatedRequest.mockResolvedValue(orders)
  return render(
    <MemoryRouter initialEntries={['/orders']}>
      <Routes><Route path="/orders" element={<OrdersPage />} /></Routes>
    </MemoryRouter>,
  )
}

describe('order history disclosure', () => {
  it('expands and collapses an order when its button is clicked repeatedly', async () => {
    renderOrders([{
      id: 123,
      status: 'PENDING',
      total_amount: 48.5,
      created_at: '2026-01-02T10:00:00Z',
      items: [{ product_id: 42, quantity: 2 }],
    }])

    const toggle = await screen.findByRole('button', { name: /Order #123/ })
    expect(toggle.type).toBe('button')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(toggle.getAttribute('aria-controls')).toBe('order-details-0')
    expect(screen.getByText(/Product #42/).closest('.order-details').hidden).toBe(true)

    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(await screen.findByText(/Product #42 · Quantity 2/)).toBeTruthy()
    expect(screen.getByText('Status: PENDING')).toBeTruthy()

    fireEvent.click(toggle)
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(screen.getByText(/Product #42/).closest('.order-details').hidden).toBe(true)
  })

  it('allows more than one order to remain expanded', async () => {
    renderOrders([
      { id: 123, items: [{ product_id: 42, quantity: 1 }] },
      { id: 124, items: [{ product_id: 43, quantity: 3 }] },
    ])

    const first = await screen.findByRole('button', { name: /Order #123/ })
    const second = await screen.findByRole('button', { name: /Order #124/ })
    fireEvent.click(first)
    fireEvent.click(second)

    expect(first.getAttribute('aria-expanded')).toBe('true')
    expect(second.getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByText(/Product #42/)).toBeTruthy()
    expect(screen.getByText(/Product #43/)).toBeTruthy()
  })
})
