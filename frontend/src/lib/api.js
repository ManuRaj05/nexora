const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8081').replace(/\/$/, '')

/** Send a request to the Nexora API Gateway. Frontend code should not call services directly. */
export async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path.startsWith('/') ? path : `/${path}`}`, {
    ...options,
    headers: {
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...options.headers,
    },
  })

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json') ? await response.json() : await response.text()

  if (!response.ok) {
    const message = typeof payload === 'object' && payload !== null
      ? payload.detail || payload.message
      : payload
    throw new Error(message || `Request failed (${response.status})`)
  }

  return payload
}

export { API_BASE_URL }
