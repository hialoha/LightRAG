/// <reference types="vitest/globals" />
import axios from 'axios'
import { createApiUrls } from '../src/api/urls'
import { createDevProxy } from '../dev-proxy'

describe('request destinations', () => {
  for (const origin of ['http://159.226.140.87:9621', 'https://rag.example.org', 'http://remote.example.org:5173']) {
    test(`uses the website origin ${origin}`, () => {
      const urls = createApiUrls('', origin)
      const client = axios.create({ baseURL: urls.apiBaseUrl })
      for (const path of ['/login', '/auth-status', '/health', '/workspaces']) {
        expect(client.getUri({ url: urls.root(path) })).toBe(`${origin}${path}`)
      }
      for (const path of ['/documents/upload', '/graphs', '/query', '/workspaces']) {
        expect(client.getUri({ url: path })).toBe(`${origin}/api${path}`)
      }
      expect(urls.api('/query/stream')).toBe(`${origin}/api/query/stream`)
    })
  }

  test('preserves an explicit separate backend and path prefix', () => {
    const urls = createApiUrls(' https://backend.example.org/rag/// ', 'http://frontend.example.org')
    const client = axios.create({ baseURL: urls.apiBaseUrl })
    expect(client.getUri({ url: urls.root('login') })).toBe('https://backend.example.org/rag/login')
    expect(client.getUri({ url: '/documents' })).toBe('https://backend.example.org/rag/api/documents')
    expect(urls.api('query/stream')).toBe('https://backend.example.org/rag/api/query/stream')
  })
})

describe('development proxy', () => {
  test('includes authentication, business APIs and API documentation by default', () => {
    const proxy = createDevProxy({})
    for (const path of ['/login', '/auth-status', '/api', '/health', '/workspaces', '/docs', '/static']) {
      expect(proxy[path]).toEqual({ target: 'http://localhost:9621', changeOrigin: true })
    }
  })

  test('uses the launcher target and preserves required endpoints with a custom list', () => {
    const proxy = createDevProxy({
      VITE_BACKEND_PROXY_TARGET: 'http://127.0.0.1:19621',
      VITE_BACKEND_URL: '',
      VITE_API_ENDPOINTS: ' /extra, ,/api '
    })
    expect(proxy['/login'].target).toBe('http://127.0.0.1:19621')
    expect(proxy['/api'].target).toBe('http://127.0.0.1:19621')
    expect(proxy['/extra'].target).toBe('http://127.0.0.1:19621')
    expect(proxy['']).toBeUndefined()
  })

  test('allows explicitly disabling the proxy', () => {
    expect(createDevProxy({ VITE_API_PROXY: 'false' })).toEqual({})
  })
})
