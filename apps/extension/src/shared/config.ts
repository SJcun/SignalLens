declare const __SIGNALLENS_API_BASE_URL__: string
declare const __SIGNALLENS_WEB_BASE_URL__: string

/** 构建时写入的唯一后端地址，避免插件运行时连接任意服务器。 */
export const API_BASE_URL = __SIGNALLENS_API_BASE_URL__.replace(/\/$/, '')

/** 提交成功后打开的 Web 地址，开发构建默认指向本地 Vue。 */
export const WEB_BASE_URL = __SIGNALLENS_WEB_BASE_URL__.replace(/\/$/, '')
