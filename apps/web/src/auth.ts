/** Web 端只保存后端签发的随机会话令牌，不保存账号密码。 */
const ACCESS_TOKEN_KEY = 'signallens.access-token'

/** 返回当前浏览器保存的 Bearer 令牌。 */
export function getAccessToken(): string | null {
  return window.localStorage.getItem(ACCESS_TOKEN_KEY)
}

/** 登录成功后保存会话，供后续 API 请求复用。 */
export function setAccessToken(token: string): void {
  window.localStorage.setItem(ACCESS_TOKEN_KEY, token)
}

/** 退出、改密或收到 401 时清除本地会话。 */
export function clearAccessToken(): void {
  window.localStorage.removeItem(ACCESS_TOKEN_KEY)
}

/** 路由守卫只做本地快速判断，真实性仍由后端逐请求校验。 */
export function hasAccessToken(): boolean {
  return Boolean(getAccessToken())
}

/** 为受保护 API 添加认证头，并在会话失效时返回登录页。 */
export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = getAccessToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(input, { ...init, headers })
  if (response.status === 401 && token) {
    clearAccessToken()
    if (window.location.pathname !== '/login') {
      const redirect = `${window.location.pathname}${window.location.search}`
      window.location.assign(`/login?redirect=${encodeURIComponent(redirect)}`)
    }
  }
  return response
}
