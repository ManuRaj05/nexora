import { createContext, useContext, useEffect, useMemo, useState } from 'react'

const CartContext = createContext(null)
const CART_STORAGE_KEY = 'nexora-cart'

function readSavedCart() {
  try {
    const savedCart = window.localStorage.getItem(CART_STORAGE_KEY)
    if (!savedCart) return []

    const parsed = JSON.parse(savedCart)
    if (!Array.isArray(parsed)) return []

    return parsed.filter((item) => (
      item &&
      (typeof item.id === 'number' || typeof item.id === 'string') &&
      typeof item.name === 'string' &&
      Number.isFinite(Number(item.price)) &&
      Number.isFinite(Number(item.stock)) && Number(item.stock) > 0 &&
      Number.isInteger(Number(item.quantity)) &&
      Number(item.quantity) > 0 && Number(item.quantity) <= Number(item.stock)
    )).map((item) => ({
      id: item.id,
      name: item.name,
      description: typeof item.description === 'string' ? item.description : '',
      price: Number(item.price),
      stock: Number(item.stock),
      category: typeof item.category === 'string' ? item.category : '',
      quantity: Number(item.quantity),
    }))
  } catch {
    return []
  }
}

export function CartProvider({ children }) {
  const [items, setItems] = useState(readSavedCart)

  useEffect(() => {
    try {
      window.localStorage.setItem(CART_STORAGE_KEY, JSON.stringify(items))
    } catch {
      // Keep the in-memory cart usable when browser storage is unavailable.
    }
  }, [items])

  function addItem(product) {
    if (product.stock < 1) return

    setItems((current) => {
      const existing = current.find((item) => item.id === product.id)
      if (existing) {
        return current.map((item) => item.id === product.id
          ? { ...item, quantity: Math.min(item.quantity + 1, product.stock), stock: product.stock }
          : item)
      }
      return [...current, { ...product, quantity: 1 }]
    })
  }

  function setQuantity(productId, quantity) {
    setItems((current) => current
      .map((item) => item.id === productId
        ? { ...item, quantity: Math.max(1, Math.min(Number(quantity) || 1, item.stock)) }
        : item))
  }

  function removeItem(productId) {
    setItems((current) => current.filter((item) => item.id !== productId))
  }

  function clearCart() {
    setItems([])
  }

  const itemCount = items.reduce((total, item) => total + item.quantity, 0)
  const value = useMemo(() => ({ items, itemCount, addItem, setQuantity, removeItem, clearCart }), [items, itemCount])

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>
}

export function useCart() {
  const context = useContext(CartContext)
  if (!context) throw new Error('useCart must be used within CartProvider')
  return context
}
