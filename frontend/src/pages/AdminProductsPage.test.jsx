import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mocks = vi.hoisted(() => ({ useAuth: vi.fn(), apiRequest: vi.fn() }))
vi.mock('../features/auth/AuthContext.jsx', () => ({ useAuth: mocks.useAuth }))
vi.mock('../lib/api.js', () => ({ apiRequest: mocks.apiRequest }))

import AdminProductsPage from './AdminProductsPage.jsx'

afterEach(() => cleanup())

beforeEach(() => {
  mocks.apiRequest.mockResolvedValue([[7, 'Desk lamp', 'Warm light', 49.5, 4, 'Home']])
  mocks.useAuth.mockReturnValue({ authenticatedRequest: vi.fn().mockResolvedValue({ id: 8 }) })
})

function renderPage() {
  return render(<MemoryRouter><AdminProductsPage /></MemoryRouter>)
}

describe('admin product management', () => {
  it('loads the catalog and submits product changes through authenticated requests', async () => {
    renderPage()
    await screen.findByText('Desk lamp')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Wall clock' } })
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Quiet movement' } })
    fireEvent.change(screen.getByLabelText('Price (INR)'), { target: { value: '79.25' } })
    fireEvent.change(screen.getByLabelText('Stock'), { target: { value: '6' } })
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'Home' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create product' }))

    await waitFor(() => expect(mocks.useAuth.mock.results[0].value.authenticatedRequest).toHaveBeenCalledOnce())
    const [path, options] = mocks.useAuth.mock.results[0].value.authenticatedRequest.mock.calls[0]
    expect(path).toBe('/products')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({
      name: 'Wall clock', description: 'Quiet movement', price: 79.25, stock: 6, category: 'Home',
    })
  })

  it('explains a server-side 403 when an admin role is no longer valid', async () => {
    const authenticatedRequest = vi.fn().mockRejectedValue(Object.assign(new Error('Forbidden'), { status: 403 }))
    mocks.useAuth.mockReturnValue({ authenticatedRequest })
    renderPage()
    await screen.findByText('Desk lamp')
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Wall clock' } })
    fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'Quiet movement' } })
    fireEvent.change(screen.getByLabelText('Price (INR)'), { target: { value: '79' } })
    fireEvent.change(screen.getByLabelText('Stock'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Category'), { target: { value: 'Home' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create product' }))
    expect(await screen.findByText('Administrator access is required. Your account may have been changed.')).toBeTruthy()
  })
})
