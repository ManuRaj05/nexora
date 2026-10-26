import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ErrorState from '../components/ui/ErrorState.jsx'
import LoadingState from '../components/ui/LoadingState.jsx'
import { useAuth } from '../features/auth/AuthContext.jsx'
import { apiRequest } from '../lib/api.js'

const emptyProduct = { name: '', description: '', price: '', stock: '', category: '' }

function productFromRow(row) {
  if (Array.isArray(row)) {
    const [id, name, description, price, stock, category] = row
    return { id, name, description, price: Number(price), stock: Number(stock), category }
  }
  return row
}

function productPayload(form) {
  return {
    name: form.name.trim(),
    description: form.description.trim(),
    price: Number(form.price),
    stock: Number(form.stock),
    category: form.category.trim(),
  }
}

export default function AdminProductsPage() {
  const { authenticatedRequest } = useAuth()
  const [products, setProducts] = useState([])
  const [form, setForm] = useState(emptyProduct)
  const [editingId, setEditingId] = useState(null)
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  async function loadProducts() {
    setLoading(true)
    setError('')
    try {
      const result = await apiRequest('/products')
      setProducts(Array.isArray(result) ? result.map(productFromRow) : [])
    } catch (requestError) {
      setError(requestError.status === 403
        ? 'You do not have permission to manage products.'
        : requestError.status === 401
          ? 'Your session has expired. Sign in again to manage products.'
          : requestError.message || 'Could not load products.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadProducts() }, [])

  function updateField(event) {
    setForm((current) => ({ ...current, [event.target.name]: event.target.value }))
  }

  function startEditing(product) {
    setEditingId(product.id)
    setForm({
      name: product.name || '',
      description: product.description || '',
      price: String(product.price ?? ''),
      stock: String(product.stock ?? ''),
      category: product.category || '',
    })
    setNotice('')
    setError('')
  }

  function resetForm() {
    setEditingId(null)
    setForm(emptyProduct)
  }

  async function saveProduct(event) {
    event.preventDefault()
    setSubmitting(true)
    setError('')
    setNotice('')
    try {
      await authenticatedRequest(editingId ? `/products/${editingId}` : '/products', {
        method: editingId ? 'PUT' : 'POST',
        body: JSON.stringify(productPayload(form)),
      })
      setNotice(editingId ? 'Product updated.' : 'Product created.')
      resetForm()
      await loadProducts()
    } catch (requestError) {
      setError(requestError.status === 403
        ? 'Administrator access is required. Your account may have been changed.'
        : requestError.status === 401
          ? 'Your session expired. Sign in again before making changes.'
          : requestError.message || 'Could not save the product.')
    } finally {
      setSubmitting(false)
    }
  }

  async function deleteProduct(product) {
    setSubmitting(true)
    setError('')
    setNotice('')
    try {
      await authenticatedRequest(`/products/${product.id}`, { method: 'DELETE' })
      setProducts((current) => current.filter((item) => item.id !== product.id))
      if (editingId === product.id) resetForm()
      setNotice(`Deleted ${product.name}.`)
    } catch (requestError) {
      setError(requestError.status === 403
        ? 'Administrator access is required. Your account may have been changed.'
        : requestError.status === 401
          ? 'Your session expired. Sign in again before making changes.'
          : requestError.message || 'Could not delete the product.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <section className="admin-products page-panel">
      <p className="eyebrow">STORE MANAGEMENT</p>
      <h1>Product <em>catalog.</em></h1>
      <p className="page-description">Create, edit, and remove products in the Nexora catalog.</p>

      {error && <ErrorState title="Product management unavailable" message={error} />}
      {error.includes('session') && <p><Link to="/login">Sign in again</Link></p>}
      {notice && <div className="form-message form-success" role="status">{notice}</div>}

      <form className="auth-form admin-product-form" onSubmit={saveProduct}>
        <h2>{editingId ? `Edit product #${editingId}` : 'Add a product'}</h2>
        <label htmlFor="admin-product-name">Name</label>
        <input id="admin-product-name" name="name" value={form.name} onChange={updateField} required />
        <label htmlFor="admin-product-description">Description</label>
        <textarea id="admin-product-description" name="description" value={form.description} onChange={updateField} required rows="3" />
        <div className="admin-product-fields">
          <div><label htmlFor="admin-product-price">Price (INR)</label><input id="admin-product-price" name="price" type="number" min="0" step="0.01" value={form.price} onChange={updateField} required /></div>
          <div><label htmlFor="admin-product-stock">Stock</label><input id="admin-product-stock" name="stock" type="number" min="0" step="1" value={form.stock} onChange={updateField} required /></div>
          <div><label htmlFor="admin-product-category">Category</label><input id="admin-product-category" name="category" value={form.category} onChange={updateField} required /></div>
        </div>
        <div className="admin-product-actions">
          <button className="primary-button" type="submit" disabled={submitting}>{submitting ? 'Saving…' : editingId ? 'Save changes' : 'Create product'}</button>
          {editingId && <button className="secondary-button" type="button" disabled={submitting} onClick={resetForm}>Cancel edit</button>}
        </div>
      </form>

      <div className="admin-product-list">
        <div className="admin-list-heading"><h2>Current products</h2><button className="text-button" type="button" onClick={loadProducts} disabled={loading}>Refresh</button></div>
        {loading ? <LoadingState label="Loading products…" /> : products.length === 0 ? (
          <p className="empty-state">No products are listed yet.</p>
        ) : products.map((product) => (
          <article className="admin-product-row" key={product.id}>
            <div><p className="product-category">{product.category || 'Uncategorized'}</p><h3>{product.name}</h3><p>{product.stock} in stock · ₹{Number(product.price).toFixed(2)}</p></div>
            <div className="admin-product-actions">
              <button className="secondary-button" type="button" disabled={submitting} onClick={() => startEditing(product)}>Edit</button>
              <button className="danger-button" type="button" disabled={submitting} onClick={() => deleteProduct(product)}>Delete</button>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}
