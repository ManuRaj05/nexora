import { useEffect, useState } from 'react'
import { apiRequest } from '../lib/api.js'
import LoadingState from '../components/ui/LoadingState.jsx'
import ErrorState from '../components/ui/ErrorState.jsx'
import { useCart } from '../features/cart/CartContext.jsx'

const highlights = [
  { number: '01', title: 'Thoughtful by design', text: 'Useful things, made with care and chosen to last.' },
  { number: '02', title: 'Everyday, elevated', text: 'A considered edit for the moments that make a day.' },
  { number: '03', title: 'A little less, better', text: 'Find your next favourite without all the extra noise.' },
]

function transformProduct(row) {
  if (Array.isArray(row)) {
    const [id, name, description, price, stock, category] = row
    return { id, name, description, price: Number(price), stock: Number(stock), category }
  }
  return { ...row, id: row.id, price: Number(row.price), stock: Number(row.stock) }
}

function formatPrice(price) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 2 }).format(price)
}

function ProductCard({ product, onAdd, inCart }) {
  const available = product.stock > 0

  return (
    <article className="product-card">
      <div className={`product-visual visual-${Math.abs(Number(product.id) || 0) % 4}`} aria-hidden="true">
        <span className="visual-orbit" />
        <span className="visual-shape" />
        <span className="visual-index">Nº {String(product.id).padStart(2, '0')}</span>
      </div>
      <div className="product-details">
        <div className="product-heading">
          <div><p className="product-category">{product.category || 'NEXORA FIND'}</p><h3>{product.name}</h3></div>
          <span className="product-price">{formatPrice(product.price)}</span>
        </div>
        <p className="product-description">{product.description}</p>
        <div className="product-footer">
          <span className={available ? 'stock-status' : 'stock-status sold-out'}>
            <span aria-hidden="true" />{available ? `${product.stock} available` : 'Out of stock'}
          </span>
          <button className="add-button" type="button" disabled={!available} onClick={() => onAdd(product)}>
            {available ? (inCart ? 'Add another +' : 'Add to cart +') : 'Unavailable'}
          </button>
        </div>
      </div>
    </article>
  )
}

export default function HomePage() {
  const [products, setProducts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const { items, addItem } = useCart()

  async function loadProducts(signal) {
    setLoading(true)
    setError('')
    try {
      const response = await apiRequest('/products', { signal })
      if (!Array.isArray(response)) throw new Error('The catalog response was not a product list.')
      setProducts(response.map(transformProduct))
    } catch (requestError) {
      if (requestError.name !== 'AbortError') setError(requestError.message || 'Could not load the product catalog.')
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    loadProducts(controller.signal)
    return () => controller.abort()
  }, [])

  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow"><span className="eyebrow-line" /> THE NEXORA EDIT</p>
          <h1>Good things<br />for <em>every day.</em></h1>
          <p className="hero-description">A thoughtful collection of essentials for living well. Find the pieces you’ll reach for, day after day.</p>
          <a className="button button-dark" href="#collection">Explore the collection <span aria-hidden="true">↗</span></a>
          <div className="hero-note"><span className="note-star" aria-hidden="true">✳</span><span>Considered finds.<br />Everyday favourites.</span></div>
        </div>
        <div className="hero-art" aria-label="Abstract still life in warm natural tones" role="img">
          <div className="art-sun" />
          <div className="art-orbit orbit-one" />
          <div className="art-orbit orbit-two" />
          <div className="art-vase"><span /></div>
          <div className="art-book book-back" />
          <div className="art-book book-front" />
          <div className="art-caption"><span>01 / 03</span><span>THE SLOW LIVING EDIT</span></div>
        </div>
        <div className="hero-index" aria-hidden="true">Nº 001 <span>—</span> EST. FOR EVERYDAY</div>
      </section>

      <section className="intro-section" aria-labelledby="intro-title">
        <div>
          <p className="eyebrow">A BETTER KIND OF FIND</p>
          <h2 id="intro-title">Make room for<br /><em>the good stuff.</em></h2>
        </div>
        <p className="intro-text">Nexora brings together useful, beautiful things that make everyday feel a little more special. Take a look around; your next favourite might be just ahead.</p>
      </section>

      <section className="highlights" aria-label="What makes Nexora different">
        {highlights.map((item) => (
          <article className="highlight" key={item.number}>
            <span className="highlight-number">{item.number}</span>
            <h3>{item.title}</h3>
            <p>{item.text}</p>
          </article>
        ))}
      </section>
      <section id="collection" className="catalog-section" aria-labelledby="catalog-title">
        <div className="catalog-heading">
          <div><p className="eyebrow">THE COLLECTION</p><h2 id="catalog-title">Good finds,<br /><em>ready for you.</em></h2></div>
          {!loading && !error && <p>{products.length} {products.length === 1 ? 'considered find' : 'considered finds'}</p>}
        </div>
        {loading && <LoadingState label="Finding the good things…" />}
        {error && <div className="catalog-state"><ErrorState title="The collection is taking a moment" message={error} /><button className="text-link retry-button" type="button" onClick={() => loadProducts()}>Try again <span aria-hidden="true">↻</span></button></div>}
        {!loading && !error && products.length === 0 && <div className="empty-catalog"><span className="empty-spark" aria-hidden="true">✳</span><h3>A little quiet on the shelves.</h3><p>There are no products to show just yet. Check back soon for new finds.</p></div>}
        {!loading && !error && products.length > 0 && (
          <div className="product-grid">
            {products.map((product) => (
              <ProductCard key={product.id} product={product} onAdd={addItem} inCart={items.some((item) => item.id === product.id)} />
            ))}
          </div>
        )}
      </section>
    </>
  )
}
