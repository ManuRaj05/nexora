import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { apiRequest } from '../lib/api.js'

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export default function RegisterPage() {
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setSuccess(false)

    const normalizedUsername = username.trim()
    const normalizedEmail = email.trim()
    if (!normalizedUsername) {
      setError('Enter a username.')
      return
    }
    if (!emailPattern.test(normalizedEmail)) {
      setError('Enter a valid email address.')
      return
    }
    if (!password) {
      setError('Choose a password.')
      return
    }

    setSubmitting(true)
    try {
      // Registration returns [id, username, email, role]; it does not issue a token.
      await apiRequest('/users/register', {
        method: 'POST',
        body: JSON.stringify({ username: normalizedUsername, email: normalizedEmail, password }),
      })
      setPassword('')
      setSuccess(true)
    } catch (requestError) {
      setError(requestError.message || 'Unable to create your account. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (success) {
    return (
      <section className="page-panel narrow-panel">
        <p className="eyebrow">YOU’RE ON THE LIST</p>
        <h1>Welcome<br /><em>to Nexora.</em></h1>
        <div className="form-message form-success" role="status">Your account has been created. Sign in to continue.</div>
        <button className="button button-dark auth-submit" type="button" onClick={() => navigate('/login', { state: { registered: true } })}>
          Continue to sign in <span aria-hidden="true">↗</span>
        </button>
      </section>
    )
  }

  return (
    <section className="page-panel narrow-panel">
      <p className="eyebrow">A PLACE FOR THE GOOD STUFF</p>
      <h1>Make yourself<br /><em>at home.</em></h1>
      <p className="page-description">Create an account and make Nexora yours.</p>
      {error && <div className="form-message form-error" role="alert">{error}</div>}

      <form className="auth-form" onSubmit={handleSubmit} noValidate>
        <label htmlFor="register-username">Username</label>
        <input
          id="register-username"
          name="username"
          type="text"
          autoComplete="username"
          value={username}
          onChange={(event) => setUsername(event.target.value)}
          required
          aria-invalid={Boolean(error)}
        />
        <label htmlFor="register-email">Email address</label>
        <input
          id="register-email"
          name="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          aria-invalid={Boolean(error)}
        />
        <label htmlFor="register-password">Password</label>
        <input
          id="register-password"
          name="password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
          aria-invalid={Boolean(error)}
        />
        <button className="button button-dark auth-submit" type="submit" disabled={submitting}>
          {submitting ? 'Creating account…' : 'Create account'} <span aria-hidden="true">↗</span>
        </button>
      </form>

      <p className="form-footnote">Already have an account? <Link to="/login">Sign in</Link></p>
    </section>
  )
}
