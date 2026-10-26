import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mocks = vi.hoisted(() => ({
  useAuth: vi.fn(),
  useCart: vi.fn(),
}))

vi.mock('../features/auth/AuthContext.jsx', () => ({ useAuth: mocks.useAuth }))
vi.mock('../features/cart/CartContext.jsx', () => ({ useCart: mocks.useCart }))

import CartPage from './CartPage.jsx'

const STORAGE_KEY = 'nexora-checkout-attempt'
const product = {
  id: 41,
  name: 'Test product',
  description: 'Disposable test item',
  price: 12.5,
  stock: 8,
  category: 'Test',
  quantity: 2,
}

let cartContext
let authContext
let randomUUID

function renderCartPage() {
  return render(
    <MemoryRouter>
      <CartPage />
    </MemoryRouter>,
  )
}

function readSavedAttempt() {
  return JSON.parse(window.sessionStorage.getItem(STORAGE_KEY))
}

function terminalFailure(message = 'Insufficient stock') {
  return Object.assign(new Error(message), { status: 409 })
}

beforeEach(() => {
  window.sessionStorage.clear()
  cartContext = {
    items: [{ ...product }],
    setQuantity: vi.fn(),
    removeItem: vi.fn(),
    clearCart: vi.fn(),
  }
  authContext = {
    user: { user_id: 5 },
    status: 'authenticated',
    isAuthenticated: true,
    authenticatedRequest: vi.fn(),
  }
  mocks.useCart.mockImplementation(() => cartContext)
  mocks.useAuth.mockImplementation(() => authContext)
  randomUUID = vi.spyOn(window.crypto, 'randomUUID')
    .mockReturnValueOnce('11111111-1111-4111-8111-111111111111')
    .mockReturnValueOnce('22222222-2222-4222-8222-222222222222')
    .mockReturnValueOnce('33333333-3333-4333-8333-333333333333')
})

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

describe('CartPage checkout idempotency', () => {
  it('sends the idempotency header and normalized order payload', async () => {
    authContext.authenticatedRequest.mockResolvedValue({ id: 101 })
    renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))

    await waitFor(() => expect(authContext.authenticatedRequest).toHaveBeenCalledOnce())
    const [path, options] = authContext.authenticatedRequest.mock.calls[0]
    expect(path).toBe('/orders')
    expect(options.method).toBe('POST')
    expect(options.headers['Idempotency-Key']).toBe('11111111-1111-4111-8111-111111111111')
    expect(JSON.parse(options.body)).toEqual({
      user_id: 5,
      items: [{ product_id: 41, quantity: 2 }],
    })
    expect(JSON.parse(options.body)).not.toHaveProperty('price')
  })

  it.each([
    ['network failure', () => new TypeError('Network unavailable')],
    ['server failure', () => Object.assign(new Error('Gateway unavailable'), { status: 503 })],
    ['in-progress conflict', () => Object.assign(new Error('An order with this Idempotency-Key is already in progress'), { status: 409 })],
  ])('reuses the saved key after an ambiguous %s', async (_label, makeError) => {
    authContext.authenticatedRequest
      .mockRejectedValueOnce(makeError())
      .mockResolvedValueOnce({ id: 102 })
    renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await screen.findByRole('alert')
    const savedAttempt = readSavedAttempt()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await waitFor(() => expect(authContext.authenticatedRequest).toHaveBeenCalledTimes(2))

    expect(authContext.authenticatedRequest.mock.calls[0][1].headers['Idempotency-Key']).toBe(savedAttempt.key)
    expect(authContext.authenticatedRequest.mock.calls[1][1].headers['Idempotency-Key']).toBe(savedAttempt.key)
  })

  it('reuses the key for the same user and payload after a retry', async () => {
    authContext.authenticatedRequest
      .mockRejectedValueOnce(new TypeError('Network unavailable'))
      .mockResolvedValueOnce({ id: 103 })
    renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await screen.findByRole('alert')
    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await waitFor(() => expect(authContext.authenticatedRequest).toHaveBeenCalledTimes(2))

    expect(authContext.authenticatedRequest.mock.calls[0][1].headers['Idempotency-Key'])
      .toBe(authContext.authenticatedRequest.mock.calls[1][1].headers['Idempotency-Key'])
  })

  it('generates a new key when the order payload changes', async () => {
    authContext.authenticatedRequest
      .mockRejectedValueOnce(new TypeError('Network unavailable'))
      .mockResolvedValueOnce({ id: 104 })
    const view = renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await screen.findByRole('alert')
    cartContext = { ...cartContext, items: [{ ...product, quantity: 3 }] }
    view.rerender(<MemoryRouter><CartPage /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await waitFor(() => expect(authContext.authenticatedRequest).toHaveBeenCalledTimes(2))

    expect(authContext.authenticatedRequest.mock.calls[1][1].headers['Idempotency-Key'])
      .toBe('22222222-2222-4222-8222-222222222222')
    expect(JSON.parse(authContext.authenticatedRequest.mock.calls[1][1].body).items[0].quantity).toBe(3)
  })

  it('generates a new key when the authenticated user changes', async () => {
    authContext.authenticatedRequest
      .mockRejectedValueOnce(new TypeError('Network unavailable'))
      .mockResolvedValueOnce({ id: 105 })
    const view = renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await screen.findByRole('alert')
    authContext = { ...authContext, user: { user_id: 6 } }
    view.rerender(<MemoryRouter><CartPage /></MemoryRouter>)
    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await waitFor(() => expect(authContext.authenticatedRequest).toHaveBeenCalledTimes(2))

    expect(authContext.authenticatedRequest.mock.calls[1][1].headers['Idempotency-Key'])
      .toBe('22222222-2222-4222-8222-222222222222')
    expect(JSON.parse(authContext.authenticatedRequest.mock.calls[1][1].body).user_id).toBe(6)
  })

  it('clears the cart and saved attempt only after confirmed success', async () => {
    authContext.authenticatedRequest.mockResolvedValue({ id: 106 })
    renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))

    await screen.findByText('Order #106 was created successfully.')
    expect(cartContext.clearCart).toHaveBeenCalledOnce()
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('uses a new key after a known terminal failure', async () => {
    authContext.authenticatedRequest
      .mockRejectedValueOnce(terminalFailure())
      .mockResolvedValueOnce({ id: 107 })
    renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await screen.findByRole('alert')
    expect(window.sessionStorage.getItem(STORAGE_KEY)).toBeNull()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await waitFor(() => expect(authContext.authenticatedRequest).toHaveBeenCalledTimes(2))

    expect(authContext.authenticatedRequest.mock.calls[0][1].headers['Idempotency-Key'])
      .toBe('11111111-1111-4111-8111-111111111111')
    expect(authContext.authenticatedRequest.mock.calls[1][1].headers['Idempotency-Key'])
      .toBe('22222222-2222-4222-8222-222222222222')
  })

  it('disables quantity and remove controls while checkout is submitting', async () => {
    let resolveRequest
    authContext.authenticatedRequest.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve
    }))
    renderCartPage()

    fireEvent.click(screen.getByRole('button', { name: /checkout/i }))
    await waitFor(() => expect(authContext.authenticatedRequest).toHaveBeenCalledOnce())

    expect(screen.getByRole('spinbutton', { name: 'Quantity for Test product' }).disabled).toBe(true)
    expect(screen.getByRole('button', { name: 'Remove Test product from cart' }).disabled).toBe(true)

    resolveRequest({ id: 108 })
    await screen.findByText('Order #108 was created successfully.')
  })
})
