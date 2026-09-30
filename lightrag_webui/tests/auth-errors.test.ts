/// <reference types="vitest/globals" />
import { AxiosError, AxiosHeaders } from 'axios'
import { getLoginErrorKey, InvalidAuthResponseError, isAuthRequest } from '../src/api/auth-errors'

function httpError(status: number, detail = '') {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('Request failed', undefined, config, undefined, {
    status, statusText: '', config, headers: {}, data: { detail }
  })
}

describe('login error messages', () => {
  test('only reports incorrect credentials for an explicit credential rejection', () => {
    expect(getLoginErrorKey(httpError(401, 'Incorrect credentials'))).toBe('login.errorInvalidCredentials')
    expect(getLoginErrorKey(httpError(401, 'Invalid token'))).toBe('login.errorAccessDenied')
    expect(getLoginErrorKey(httpError(401, 'Incorrect credentials'), true)).toBe('login.errorAccessDenied')
  })

  for (const [status, key] of [
    [403, 'errorAccessDenied'], [404, 'errorServiceAddress'], [405, 'errorServiceAddress'],
    [429, 'errorTooManyAttempts'], [500, 'errorServer'], [502, 'errorServer'], [422, 'errorUnexpected']
  ] as const) {
    test(`classifies HTTP ${status}`, () => {
      expect(getLoginErrorKey(httpError(status))).toBe(`login.${key}`)
    })
  }

  test('distinguishes connection, timeout, malformed response and browser errors', () => {
    expect(getLoginErrorKey(new AxiosError('Network Error', 'ERR_NETWORK'))).toBe('login.errorConnection')
    expect(getLoginErrorKey(new AxiosError('Timeout', 'ECONNABORTED'))).toBe('login.errorTimeout')
    expect(getLoginErrorKey(new AxiosError('Timeout', 'ETIMEDOUT'))).toBe('login.errorTimeout')
    expect(getLoginErrorKey(new InvalidAuthResponseError())).toBe('login.errorServiceAddress')
    expect(getLoginErrorKey(new Error('Storage unavailable'))).toBe('login.errorUnexpected')
  })

  test('preserves authentication errors without changing business error handling', () => {
    expect(isAuthRequest('https://rag.example.org/login')).toBe(true)
    expect(isAuthRequest('https://rag.example.org/auth-status?check=1')).toBe(true)
    expect(isAuthRequest('/api/documents/login-notes')).toBe(false)
    expect(isAuthRequest(undefined)).toBe(false)
  })
})
