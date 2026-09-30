/// <reference types="vitest/globals" />
import { JSDOM } from 'jsdom'
import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { createInstance } from 'i18next'
import React, { act } from 'react'
import type { Root } from 'react-dom/client'
import en from '../src/locales/en.json'
import zh from '../src/locales/zh.json'

const origin = 'http://159.226.140.87:9621'
const token = `e30.${btoa(JSON.stringify({ sub: 'tester', exp: 4102444800 }))}.test`
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: `${origin}/webui/#/login` })
const originalAdapter = axios.defaults.adapter
const originalFetch = globalThis.fetch
const originalBackend = process.env.VITE_BACKEND_URL
const savedGlobals = new Map<string, PropertyDescriptor | undefined>()
let root: Root | undefined
let api: typeof import('../src/api/lightrag')
let auth: typeof import('../src/stores/state')
let settings: typeof import('../src/stores/settings')
let navigation: typeof import('../src/services/navigation')
let createRoot: typeof import('react-dom/client').createRoot
let LoginPage: typeof import('../src/features/LoginPage').default
let router: typeof import('react-router-dom')
let I18nextProvider: typeof import('react-i18next').I18nextProvider
let requests: InternalAxiosRequestConfig[] = []
let destinations: string[] = []
let handler: (config: InternalAxiosRequestConfig) => AxiosResponse | Promise<AxiosResponse>
const i18n = createInstance()

function respond(config: InternalAxiosRequestConfig, data: unknown, status = 200, headers = {}) {
  const response = { config, data, status, statusText: String(status), headers }
  if (status >= 400) throw new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, undefined, response)
  return response
}

beforeAll(async () => {
  process.env.VITE_BACKEND_URL = ''
  const browserGlobals: Record<string, unknown> = {
    window: dom.window, document: dom.window.document, navigator: dom.window.navigator,
    localStorage: dom.window.localStorage, sessionStorage: dom.window.sessionStorage,
    HTMLElement: dom.window.HTMLElement, Element: dom.window.Element,
    Node: dom.window.Node, MutationObserver: dom.window.MutationObserver,
    getComputedStyle: dom.window.getComputedStyle.bind(dom.window),
    IS_REACT_ACT_ENVIRONMENT: true
  }
  for (const [key, value] of Object.entries(browserGlobals)) {
    savedGlobals.set(key, Object.getOwnPropertyDescriptor(globalThis, key))
    Object.defineProperty(globalThis, key, { configurable: true, writable: true, value })
  }
  axios.defaults.adapter = async config => {
    requests.push(config)
    return handler(config)
  }
  api = await import('../src/api/lightrag')
  auth = await import('../src/stores/state')
  settings = await import('../src/stores/settings')
  navigation = await import('../src/services/navigation')
  createRoot = (await import('react-dom/client')).createRoot
  LoginPage = (await import('../src/features/LoginPage')).default
  router = await import('react-router-dom')
  I18nextProvider = (await import('react-i18next')).I18nextProvider
  await i18n.init({ lng: 'zh', fallbackLng: 'en', resources: { en: { translation: en }, zh: { translation: zh } } })
})

beforeEach(() => {
  localStorage.clear()
  sessionStorage.clear()
  auth.useAuthStore.setState({ isAuthenticated: false, isGuestMode: false, username: null })
  settings.useSettingsStore.setState({ apiKey: null, workspace: null, defaultWorkspace: '' })
  requests = []
  destinations = []
  navigation.navigationService.setNavigate(destination => { destinations.push(String(destination)) })
  handler = config => respond(config, config.url?.endsWith('/auth-status')
    ? { auth_configured: true, auth_mode: 'enabled' }
    : { access_token: token, auth_mode: 'enabled', core_version: 'test' })
})

afterEach(async () => {
  if (root) await act(async () => root?.unmount())
  root = undefined
  document.body.innerHTML = ''
  globalThis.fetch = originalFetch
})

afterAll(() => {
  if (originalBackend === undefined) delete process.env.VITE_BACKEND_URL
  else process.env.VITE_BACKEND_URL = originalBackend
  axios.defaults.adapter = originalAdapter
  dom.window.close()
  for (const [key, descriptor] of savedGlobals) {
    if (descriptor) Object.defineProperty(globalThis, key, descriptor)
    else Reflect.deleteProperty(globalThis, key)
  }
})

async function mountLogin() {
  const container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
  const { MemoryRouter, Routes, Route } = router
  await act(async () => {
    root?.render(
      <I18nextProvider i18n={i18n}>
        <MemoryRouter initialEntries={['/login']}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/" element={<div data-testid="home">Home</div>} />
          </Routes>
        </MemoryRouter>
      </I18nextProvider>
    )
  })
}

async function submitLogin() {
  await act(async () => {
    for (const [id, value] of [['username-input', 'tester'], ['password-input', 'test-password']]) {
      const input = document.getElementById(id) as HTMLInputElement
      Object.getOwnPropertyDescriptor(dom.window.HTMLInputElement.prototype, 'value')?.set?.call(input, value)
      input.dispatchEvent(new dom.window.Event('input', { bubbles: true }))
    }
  })
  await act(async () => {
    document.querySelector('form')?.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }))
  })
}

test('logs in through /login with a bounded timeout and redirects on success', async () => {
  await mountLogin()
  await submitLogin()
  expect(document.querySelector('[data-testid="home"]')).not.toBeNull()
  const request = requests.find(config => config.url?.endsWith('/login'))!
  expect(axios.getUri(request)).toBe(`${origin}/login`)
  expect(request.timeout).toBe(15000)
  expect((request.data as FormData).get('username')).toBe('tester')
  expect(localStorage.getItem('LIGHTRAG-API-TOKEN')).toBe(token)
})

for (const [status, detail, message] of [
  [401, 'Incorrect credentials', zh.login.errorInvalidCredentials],
  [404, 'Not Found', zh.login.errorServiceAddress],
  [503, 'Unavailable', zh.login.errorServer]
] as const) {
  test(`shows the correct persistent form error for HTTP ${status}`, async () => {
    await mountLogin()
    handler = config => respond(config, { detail }, status)
    await submitLogin()
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(message)
    expect(document.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(false)
    expect(auth.useAuthStore.getState().isAuthenticated).toBe(false)
  })
}

test('reports a connection failure and allows another login attempt', async () => {
  await mountLogin()
  handler = config => { throw new AxiosError('Network Error', 'ERR_NETWORK', config) }
  await submitLogin()
  expect(document.querySelector('[role="alert"]')?.textContent).toBe(zh.login.errorConnection)
  handler = config => respond(config, { access_token: token })
  await submitLogin()
  expect(document.querySelector('[data-testid="home"]')).not.toBeNull()
})

test('reports an unavailable authentication service and reconnects without submitting credentials', async () => {
  handler = config => respond(config, { detail: 'Unavailable' }, 503)
  await mountLogin()
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(zh.login.errorServer)
  expect(document.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(true)
  expect(requests.every(config => config.url?.endsWith('/auth-status'))).toBe(true)
  handler = config => respond(config, { auth_configured: true })
  await act(async () => {
    document.querySelector<HTMLButtonElement>('[role="alert"] button')?.click()
  })
  expect(document.querySelector('[role="alert"]')).toBeNull()
  expect(document.querySelector<HTMLButtonElement>('button[type="submit"]')?.disabled).toBe(false)
})

test('rejects HTML and tokenless login responses instead of reporting a password error', async () => {
  handler = config => respond(config, '<html>Proxy error</html>')
  await expect(api.getAuthStatus()).rejects.toThrow('Invalid authentication service response')
  handler = config => respond(config, { auth_configured: false })
  await expect(api.getAuthStatus()).rejects.toThrow('Invalid authentication service response')
  handler = config => respond(config, { unexpected: true })
  await expect(api.loginToServer('tester', 'test-password')).rejects.toThrow('Invalid authentication service response')
})

test('does not blame credentials when browser session storage fails after authentication', async () => {
  await mountLogin()
  const original = dom.window.Storage.prototype.setItem
  dom.window.Storage.prototype.setItem = function (key: string, value: string) {
    if (key === 'VERSION_CHECKED_FROM_LOGIN') throw new Error('Storage unavailable')
    original.call(this, key, value)
  }
  try {
    await submitLogin()
    expect(document.querySelector('[role="alert"]')?.textContent).toBe(zh.login.errorSession)
    expect(auth.useAuthStore.getState().isAuthenticated).toBe(false)
  } finally {
    dom.window.Storage.prototype.setItem = original
  }
})

test('preserves guest access when authentication is disabled', async () => {
  handler = config => respond(config, { auth_configured: false, access_token: token, auth_mode: 'disabled' })
  await mountLogin()
  expect(document.querySelector('[data-testid="home"]')).not.toBeNull()
  expect(auth.useAuthStore.getState().isGuestMode).toBe(true)
})

test('preserves automatic token renewal on business responses', async () => {
  localStorage.setItem('LIGHTRAG-API-TOKEN', 'old-token')
  auth.useAuthStore.setState({ isAuthenticated: true })
  handler = config => respond(config, {}, 200, { 'x-new-token': token })
  await api.getDocuments()
  expect(localStorage.getItem('LIGHTRAG-API-TOKEN')).toBe(token)
  expect(auth.useAuthStore.getState().tokenExpiresAt).toBe(4102444800 * 1000)
})

test('keeps business routes, upload data, API keys and workspace headers intact', async () => {
  localStorage.setItem('LIGHTRAG-API-TOKEN', token)
  settings.useSettingsStore.setState({ apiKey: 'test-key', workspace: 'workspace-two', defaultWorkspace: 'workspace-one' })
  handler = config => respond(config, {})
  await api.getDocuments()
  await api.queryGraphs('test', 1, 10)
  await api.getWorkspaces()
  await api.uploadDocument(new File(['test'], 'test.txt', { type: 'text/plain' }))
  expect(requests.map(config => axios.getUri(config))).toEqual([
    `${origin}/api/documents`, `${origin}/api/graphs?label=test&max_depth=1&max_nodes=10`,
    `${origin}/api/workspaces`, `${origin}/api/documents/upload`
  ])
  for (const request of requests) {
    expect(request.headers.get('Authorization')).toBe(`Bearer ${token}`)
    expect(request.headers.get('X-API-Key')).toBe('test-key')
    expect(request.headers.get('LIGHTRAG-WORKSPACE')).toBe('workspace-two')
  }
  settings.useSettingsStore.setState({ workspace: 'workspace-one' })
  await api.getDocuments()
  expect(requests.at(-1)?.headers.has('LIGHTRAG-WORKSPACE')).toBe(false)
})

test('keeps streaming requests on /api/query/stream with workspace and authentication', async () => {
  localStorage.setItem('LIGHTRAG-API-TOKEN', token)
  settings.useSettingsStore.setState({ workspace: 'workspace-two', defaultWorkspace: 'workspace-one' })
  const chunks: string[] = []
  globalThis.fetch = (async (url, options) => {
    expect(String(url)).toBe(`${origin}/api/query/stream`)
    expect(new Headers(options?.headers).get('Authorization')).toBe(`Bearer ${token}`)
    expect(new Headers(options?.headers).get('LIGHTRAG-WORKSPACE')).toBe('workspace-two')
    return new Response('{"response":"hello"}\n', { headers: { 'Content-Type': 'application/x-ndjson' } })
  }) as typeof fetch
  await api.queryTextStream({ query: 'test', mode: 'mix' }, chunk => chunks.push(chunk))
  expect(chunks).toEqual(['hello'])
})

test('renews guest tokens through the root auth endpoint and retries the business request', async () => {
  localStorage.setItem('LIGHTRAG-API-TOKEN', 'expired')
  auth.useAuthStore.setState({ isAuthenticated: true, isGuestMode: true })
  handler = config => {
    if (config.url?.endsWith('/auth-status')) return respond(config, { auth_configured: false, access_token: token })
    if (config.headers.get('Authorization') === 'Bearer expired') return respond(config, {}, 401)
    return respond(config, { statuses: {} })
  }
  await api.getDocuments()
  expect(requests.map(config => axios.getUri(config))).toEqual([
    `${origin}/api/documents`, `${origin}/auth-status`, `${origin}/api/documents`
  ])
  expect(localStorage.getItem('LIGHTRAG-API-TOKEN')).toBe(token)
  expect(destinations).toEqual([])
})

test('continues to redirect an expired regular session to login', async () => {
  localStorage.setItem('LIGHTRAG-API-TOKEN', 'expired')
  auth.useAuthStore.setState({ isAuthenticated: true, isGuestMode: false })
  handler = config => respond(config, {}, 401)
  await expect(api.getDocuments()).rejects.toThrow('Authentication required')
  expect(destinations).toEqual(['/login'])
  expect(auth.useAuthStore.getState().isAuthenticated).toBe(false)
})
