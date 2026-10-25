import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../features/auth/AuthContext.jsx'

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function LoginPage() {
  const { login, status } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [success, setSuccess] = useState('')

  const redirectPath = location.state?.from?.pathname?.startsWith('/')
    ? `${location.state.from.pathname}${location.state.from.search || ''}${location.state.from.hash || ''}`
    : '/'
  const registered = location.state?.registered === true

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setSuccess('')

    const normalizedEmail = email.trim()
    if (!emailPattern.test(normalizedEmail)) {
      setError('Enter a valid email address.')
      return
    }
    if (!password) {
      setError('Enter your password.')
      return
    }

    setSubmitting(true)
    try {
      await login(normalizedEmail, password)
      setPassword('')
      setSuccess('Signed in successfully. Taking you to your page…')
      navigate(redirectPath, { replace: true })
    } catch (requestError) {
      setError(requestError.message || 'Unable to sign in. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const busy = submitting || status === 'loading'

  return (
    <section className="page-panel narrow-panel">
      <p className="eyebrow">WELCOME BACK</p>
      <h1>Good to see<br /><em>you again.</em></h1>
      <p className="page-description">Sign in to pick up where you left off.</p>

      {registered && <div className="form-message form-success" role="status">Your account is ready. Sign in to continue.</div>}
      {location.state?.sessionMessage && <div className="form-message form-error" role="alert">{location.state.sessionMessage}</div>}
      {success && <div className="form-message form-success" role="status">{success}</div>}
      {error && <div className="form-message form-error" role="alert">{error}</div>}

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <label htmlFor="login-email">Email address</label>
        <input
          id="login-email"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          aria-invalid={Boolean(error)}
        />
        <label htmlFor="login-password">Password</label>
        <input
          id="login-password"
          name="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          aria-invalid={Boolean(error)}
        />
        <button className="button button-dark auth-submit" type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'} <span aria-hidden="true">↗</span>
        </button>
      </form>

      <p className="form-footnote">New to Nexora? <Link to="/register">Create an account</Link></p>
    </section>
  )
}
