export interface HealthResponse {
  status: 'ok'
  service: 'signallens-api'
}

/** 请求后端健康状态，确认 Web 与新服务之间的连接。 */
export async function getHealth(): Promise<HealthResponse> {
  const response = await fetch('/api/v1/health')
  if (!response.ok) throw new Error(`API 请求失败（${response.status}）`)
  return response.json() as Promise<HealthResponse>
}

