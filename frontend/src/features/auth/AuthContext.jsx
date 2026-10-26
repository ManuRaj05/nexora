import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { apiRequest } from '../../lib/api.js'

const AuthContext = createContext(null)
const AUTH_STORAGE_KEY = 'nexora-auth-token'

function readStoredToken() {
  try {
    return window.sessionStorage.getItem(AUTH_STORAGE_KEY)
  } catch {
    return null
  }
}

function clearStoredToken() {
  try {
    window.sessionStorage.removeItem(AUTH_STORAGE_KEY)
  } catch {
    // Authentication still clears in memory if browser storage is unavailable.
  }
}

async function verifyToken(token, signal) {
  const identity = await apiRequest('/users/me', {
    headers: { Authorization: `Bearer ${token}` },
    signal,
  })

  return {
    user_id: identity.user_id,
    username: identity.username,
    role: identity.role,
  }
}

function safeAuthError(error, token = '') {
  let message = typeof error?.message === 'string'
    ? error.message
    : 'Unable to complete that request. Please try again.'
  if (token) message = message.split(token).join('[redacted]')
  return message.replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[redacted]')
}

export function AuthProvider({ children }) {
  const [status, setStatus] = useState('loading')
  const [user, setUser] = useState(null)
  const [token, setToken] = useState(null)
  const [sessionMessage, setSessionMessage] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    const token = readStoredToken()

    if (!token) {
      setToken(null)
      setStatus('anonymous')
      setSessionMessage('')
      return () => controller.abort()
    }

    verifyToken(token, controller.signal)
      .then((identity) => {
        setToken(token)
        setUser(identity)
        setStatus('authenticated')
        setSessionMessage('')
      })
      .catch((error) => {
        if (error.name === 'AbortError') return
        if (error.status === 401) clearStoredToken()
        setToken(null)
        setUser(null)
        setStatus('anonymous')
        setSessionMessage(error.status === 401
          ? 'Your session is invalid or expired. Please sign in again.'
          : 'We could not verify your session. Check your connection and sign in again.')
      })

    return () => controller.abort()
  }, [])

  const login = useCallback(async (email, password) => {
    setStatus('loading')
    setToken(null)
    setUser(null)
    setSessionMessage('')
    clearStoredToken()

    let token = ''
    try {
      const result = await apiRequest('/users/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })

      if (typeof result?.token !== 'string' || !result.token) {
        throw new Error('The sign-in response was incomplete. Please try again.')
      }

      token = result.token
      const identity = await verifyToken(token)
      try {
        window.sessionStorage.setItem(AUTH_STORAGE_KEY, token)
      } catch {
        // Keep this session authenticated in memory if sessionStorage is unavailable.
      }
      setToken(token)
      setUser(identity)
      setStatus('authenticated')
      setSessionMessage('')
      return identity
    } catch (error) {
      clearStoredToken()
      setToken(null)
      setUser(null)
      setStatus('anonymous')
      setSessionMessage('')
      throw new Error(safeAuthError(error, token))
    }
  }, [])

  const logout = useCallback(() => {
    clearStoredToken()
    setToken(null)
    setUser(null)
    setStatus('anonymous')
    setSessionMessage('')
  }, [])

  const authenticatedRequest = useCallback((path, options = {}) => {
    if (!token) throw new Error('Authentication is required to make this request.')

    return apiRequest(path, {
      ...options,
      headers: {
        ...options.headers,
        Authorization: `Bearer ${token}`,
      },
    })
  }, [token])

  const value = useMemo(() => ({
    user,
    status,
    sessionMessage,
    isAuthenticated: status === 'authenticated',
    authenticatedRequest,
    login,
    logout,
  }), [user, status, sessionMessage, authenticatedRequest, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
