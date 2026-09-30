import axios from 'axios'

export class InvalidAuthResponseError extends Error {
  constructor() {
    super('Invalid authentication service response')
    this.name = 'InvalidAuthResponseError'
  }
}

export const isAuthRequest = (url?: string): boolean =>
  /\/(login|auth-status)\/?$/.test((url ?? '').split(/[?#]/)[0])

export function getLoginErrorKey(error: unknown, checkingService = false): string {
  if (error instanceof InvalidAuthResponseError) return 'login.errorServiceAddress'
  if (!axios.isAxiosError(error)) return 'login.errorUnexpected'

  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return 'login.errorTimeout'
  }
  if (!error.response) return 'login.errorConnection'

  const { status, data } = error.response
  if (!checkingService && status === 401 && data?.detail === 'Incorrect credentials') {
    return 'login.errorInvalidCredentials'
  }
  if (status === 404 || status === 405) return 'login.errorServiceAddress'
  if (status === 429) return 'login.errorTooManyAttempts'
  if (status >= 500) return 'login.errorServer'
  if (status === 401 || status === 403) return 'login.errorAccessDenied'
  return 'login.errorUnexpected'
}
