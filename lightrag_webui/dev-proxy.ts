const defaultEndpoints = [
  '/api', '/login', '/auth-status', '/health', '/workspaces',
  '/docs', '/redoc', '/openapi.json', '/static'
]

export function createDevProxy(env: Record<string, string>) {
  if (env.VITE_API_PROXY === 'false') return {}

  const target = env.VITE_BACKEND_PROXY_TARGET?.trim()
    || env.VITE_BACKEND_URL?.trim()
    || 'http://localhost:9621'
  const endpoints = new Set([
    ...defaultEndpoints,
    ...(env.VITE_API_ENDPOINTS ?? '').split(',').map(value => value.trim()).filter(Boolean)
  ])

  return Object.fromEntries(
    [...endpoints].map(endpoint => [endpoint, { target, changeOrigin: true }])
  )
}
