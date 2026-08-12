declare const __SIGNALLENS_API_BASE_URL__: string

/** 构建时写入的唯一后端地址，避免插件运行时连接任意服务器。 */
export const API_BASE_URL = __SIGNALLENS_API_BASE_URL__.replace(/\/$/, '')

