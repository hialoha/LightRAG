export function createApiUrls(configuredBackend: string, origin: string) {
  const backend = (configuredBackend.trim() || origin).replace(/\/+$/, '')
  const root = (path: string) => `${backend}/${path.replace(/^\/+/, '')}`
  const api = (path: string) => root(`/api/${path.replace(/^\/+/, '')}`)

  // Absolute root URLs prevent Axios from prepending its /api baseURL.
  return { root, api, apiBaseUrl: root('/api') }
}
