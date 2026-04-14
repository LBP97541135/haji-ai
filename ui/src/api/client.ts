// api/client.ts - 封装所有后端 API 调用
const BASE_URL = 'http://localhost:8766'

// 过滤 <think>...</think> 思考块（minimax 模型会返回这个）
export function filterThink(content: string): string {
  return content.replace(/<think>[\s\S]*?<\/think>/g, '').trim()
}

// 获取或初始化用户 ID（存于 localStorage）
function getUserId(): string {
  let uid = localStorage.getItem('haji_user_id')
  if (!uid) {
    uid = 'user_001'
    localStorage.setItem('haji_user_id', uid)
  }
  return uid
}

export interface AgentSummary {
  code: string
  name: string
  avatar: string
  bio: string
  tags: string[]
  mode: string
}

export interface ChatResponse {
  session_id: string
  content: string
  agent_code: string
}

export interface DesignerCreateResponse {
  ok: boolean
  agent_code?: string
  definition?: Record<string, unknown>
  errors?: Array<{ field: string; message: string }>
}

export interface HistoryMessage {
  role: string
  content: string
}

export interface UserProfile {
  user_id: string
  display_name: string
  facts: string[]
  preferences: Record<string, string>
  last_seen_agent: string
  message_count: number
}

export const api = {
  // 获取所有 Agent
  getAgents: async (): Promise<AgentSummary[]> => {
    const res = await fetch(`${BASE_URL}/api/agents`)
    return res.json()
  },

  // 获取单个 Agent 详情
  getAgent: async (code: string) => {
    const res = await fetch(`${BASE_URL}/api/agents/${code}`)
    return res.json()
  },

  // 非流式聊天
  chat: async (agentCode: string, message: string, _sessionId: string): Promise<ChatResponse> => {
    const res = await fetch(`${BASE_URL}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_code: agentCode,
        message,
        session_id: "",
        user_id: getUserId(),
      }),
    })
    return res.json()
  },

  // 流式聊天（fetch + ReadableStream）
  chatStream: (
    agentCode: string,
    message: string,
    _sessionId: string,
    onToken: (token: string) => void,
    onDone: (content: string, resolvedSessionId: string) => void,
    onError?: (err: string) => void,
  ) => {
    fetch(`${BASE_URL}/api/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        agent_code: agentCode,
        message,
        session_id: "",
        user_id: getUserId(),
      }),
    }).then(async (res) => {
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              if (data.type === 'token') onToken(data.content)
              if (data.type === 'done') onDone(filterThink(data.content), data.session_id || '')
              if (data.type === 'error') onError?.(data.content)
            } catch {
              // ignore parse errors
            }
          }
        }
      }
    }).catch((err) => {
      onError?.(String(err))
    })
  },

  // 创建 Agent
  createAgent: async (description: string): Promise<DesignerCreateResponse> => {
    const res = await fetch(`${BASE_URL}/api/designer/create`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ description }),
    })
    return res.json()
  },

  // 获取会话历史
  getSessionHistory: async (sessionId: string): Promise<{ messages: HistoryMessage[] }> => {
    const res = await fetch(`${BASE_URL}/api/sessions/${sessionId}/history`)
    return res.json()
  },

  // 删除 Agent
  deleteAgent: async (code: string) => {
    const res = await fetch(`${BASE_URL}/api/agents/${code}`, { method: 'DELETE' })
    return res.json()
  },

  // 健康检查
  health: async () => {
    const res = await fetch(`${BASE_URL}/health`)
    return res.json()
  },

  // 获取 Profile（模型配置等）
  getProfile: async () => {
    const res = await fetch(`${BASE_URL}/api/profile`)
    return res.json()
  },

  // 获取 AI 对用户的了解（用户画像）
  getUserProfile: async (userId?: string): Promise<UserProfile> => {
    const uid = userId || getUserId()
    const res = await fetch(`${BASE_URL}/api/users/${uid}/profile`)
    return res.json()
  },

  // 设置用户显示名称
  setDisplayName: async (name: string) => {
    const uid = getUserId()
    const res = await fetch(`${BASE_URL}/api/users/${uid}/profile/name`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    })
    return res.json()
  },
}

export { getUserId }
