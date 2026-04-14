// pages/Chat/index.tsx - 会话页（微信风格）
import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, MessageCircle, Trash2 } from 'lucide-react'
import { api } from '../../api/client'
import type { AgentSummary } from '../../api/client'
import MessageBubble from '../../components/MessageBubble'
import AvatarBubble from '../../components/AvatarBubble'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  timestamp?: Date
  isGreeting?: boolean  // 欢迎语标记，不存 localStorage
}

interface SessionState {
  sessionId: string
  messages: Message[]
}

export default function ChatPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [selectedAgent, setSelectedAgent] = useState<AgentSummary | null>(null)
  const [sessions, setSessions] = useState<Record<string, SessionState>>(() => {
    try {
      const saved = localStorage.getItem('haji_sessions')
      if (saved) {
        const parsed = JSON.parse(saved)
        // 恢复每个消息的 timestamp（Date 序列化成了字符串）
        Object.values(parsed).forEach((session: unknown) => {
          const s = session as SessionState
          s.messages = s.messages.map((m) => ({
            ...m,
            timestamp: m.timestamp ? new Date(m.timestamp as unknown as string) : undefined,
          }))
        })
        return parsed
      }
    } catch {
      // ignore parse errors
    }
    return {}
  })
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [loadingAgents, setLoadingAgents] = useState(true)
  const [backendError, setBackendError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // 加载 Agent 列表
  useEffect(() => {
    api.getAgents()
      .then((data) => {
        setAgents(data)
        setLoadingAgents(false)
        if (data.length > 0) setSelectedAgent(data[0])
      })
      .catch((err) => {
        setBackendError('无法连接后端，请确保后端已启动 (port 8766)')
        setLoadingAgents(false)
        console.error(err)
      })
  }, [])

  // 持久化 sessions 到 localStorage（过滤欢迎语，避免重复显示）
  useEffect(() => {
    try {
      const sessionsToSave: Record<string, SessionState> = {}
      for (const [code, session] of Object.entries(sessions)) {
        sessionsToSave[code] = {
          ...session,
          messages: session.messages.filter((m) => !m.isGreeting),
        }
      }
      localStorage.setItem('haji_sessions', JSON.stringify(sessionsToSave))
    } catch {
      // localStorage 满了或不可用，忽略
    }
  }, [sessions])

  // 切换 Agent 时，如果历史为空则拉取欢迎语
  useEffect(() => {
    if (!selectedAgent) return
    const session = sessions[selectedAgent.code]
    const realMessages = (session?.messages ?? []).filter((m) => !m.isGreeting)
    if (realMessages.length > 0) return  // 有真实历史，不需要欢迎语

    const agentCode = selectedAgent.code
    fetch(`http://10.40.108.146:8766/api/agents/${agentCode}/greeting?user_id=user_001`)
      .then((r) => r.json())
      .then((data) => {
        if (!data.greeting) return
        setSessions((prev) => {
          const existing = prev[agentCode]
          // 再次检查：如果此时已有真实消息（用户切换过来又发消息），就不插入欢迎语
          const currentReal = (existing?.messages ?? []).filter((m) => !m.isGreeting)
          if (currentReal.length > 0) return prev
          return {
            ...prev,
            [agentCode]: {
              sessionId: existing?.sessionId ?? '',
              messages: [
                {
                  id: `greeting_${agentCode}`,
                  role: 'assistant' as const,
                  content: data.greeting,
                  timestamp: new Date(),
                  isGreeting: true,
                },
              ],
            },
          }
        })
      })
      .catch(() => {})  // 失败静默处理，不影响主聊天功能
  }, [selectedAgent])  // eslint-disable-line react-hooks/exhaustive-deps

  // 滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [sessions, selectedAgent])

  const currentSession = selectedAgent ? sessions[selectedAgent.code] : null
  const messages = currentSession?.messages ?? []

  const sendMessage = useCallback(() => {
    if (!input.trim() || !selectedAgent || isSending) return

    const userText = input.trim()
    setInput('')
    setIsSending(true)

    const agentCode = selectedAgent.code
    const sessionId = sessions[agentCode]?.sessionId || ''
    const userMsgId = Date.now().toString()
    const aiMsgId = (Date.now() + 1).toString()

    // 追加用户消息 + 占位 AI 消息
    setSessions((prev) => {
      const existing = prev[agentCode] ?? { sessionId, messages: [] }
      return {
        ...prev,
        [agentCode]: {
          ...existing,
          messages: [
            ...existing.messages,
            { id: userMsgId, role: 'user', content: userText, timestamp: new Date() },
            { id: aiMsgId, role: 'assistant', content: '', isStreaming: true, timestamp: new Date() },
          ],
        },
      }
    })

    // 流式聊天
    api.chatStream(
      agentCode,
      userText,
      sessionId,
      // onToken
      (token) => {
        setSessions((prev) => {
          const session = prev[agentCode]
          if (!session) return prev
          return {
            ...prev,
            [agentCode]: {
              ...session,
              messages: session.messages.map((m) =>
                m.id === aiMsgId ? { ...m, content: m.content + token } : m,
              ),
            },
          }
        })
      },
      // onDone
      (finalContent, newSessionId) => {
        setSessions((prev) => {
          const session = prev[agentCode]
          if (!session) return prev
          return {
            ...prev,
            [agentCode]: {
              sessionId: newSessionId || session.sessionId,
              messages: session.messages.map((m) =>
                m.id === aiMsgId
                  ? { ...m, content: finalContent || m.content, isStreaming: false }
                  : m,
              ),
            },
          }
        })
        setIsSending(false)
      },
      // onError
      (err) => {
        setSessions((prev) => {
          const session = prev[agentCode]
          if (!session) return prev
          return {
            ...prev,
            [agentCode]: {
              ...session,
              messages: session.messages.map((m) =>
                m.id === aiMsgId
                  ? { ...m, content: `[错误] ${err}`, isStreaming: false }
                  : m,
              ),
            },
          }
        })
        setIsSending(false)
      },
    )
  }, [input, selectedAgent, isSending, sessions])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex h-full bg-gray-100">
      {/* 左侧：Agent 列表 */}
      <aside className="w-20 md:w-64 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-700 hidden md:block">会话</h2>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loadingAgents && (
            <div className="p-4 text-center text-gray-400 text-xs">加载中...</div>
          )}
          {backendError && (
            <div className="p-3 text-xs text-red-500">{backendError}</div>
          )}
          {!loadingAgents && agents.length === 0 && !backendError && (
            <div className="p-4 text-center text-gray-400 text-xs">
              暂无 Agent<br />去联系人页创建一个
            </div>
          )}
          {agents.map((agent) => {
            const isSelected = selectedAgent?.code === agent.code
            const agentMessages = sessions[agent.code]?.messages ?? []
            const lastMsg = agentMessages[agentMessages.length - 1]

            return (
              <button
                key={agent.code}
                onClick={() => setSelectedAgent(agent)}
                className={`w-full flex items-center gap-3 px-3 py-3 hover:bg-gray-50 transition-colors ${
                  isSelected ? 'bg-gray-100' : ''
                }`}
              >
                <AvatarBubble name={agent.name} code={agent.code} size="md" />
                <div className="flex-1 text-left min-w-0 hidden md:block">
                  <div className="text-sm font-medium text-gray-800 truncate">{agent.name}</div>
                  <div className="text-xs text-gray-400 truncate">
                    {lastMsg ? (lastMsg.role === 'user' ? `我: ${lastMsg.content}` : lastMsg.content) : agent.bio || '点击开始聊天'}
                  </div>
                </div>
              </button>
            )
          })}
        </div>
      </aside>

      {/* 右侧：聊天窗口 */}
      <main className="flex-1 flex flex-col min-w-0">
        {selectedAgent ? (
          <>
            {/* 头部 */}
            <header className="flex items-center gap-3 px-4 py-3 bg-white border-b border-gray-200">
              <AvatarBubble name={selectedAgent.name} code={selectedAgent.code} size="sm" />
              <div>
                <div className="font-semibold text-gray-800">{selectedAgent.name}</div>
                <div className="text-xs text-gray-400">{selectedAgent.bio}</div>
              </div>
              <button
                onClick={() => {
                  if (!selectedAgent) return
                  setSessions(prev => {
                    const next = { ...prev }
                    delete next[selectedAgent.code]
                    return next
                  })
                }}
                className="ml-auto p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                title="清除聊天记录"
              >
                <Trash2 size={16} />
              </button>
            </header>

            {/* 消息区 */}
            <div className="flex-1 overflow-y-auto px-4 py-4">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-gray-400">
                  <AvatarBubble name={selectedAgent.name} code={selectedAgent.code} size="xl" className="mb-3" />
                  <div className="text-sm font-medium text-gray-600">{selectedAgent.name}</div>
                  <div className="text-xs mt-1">{selectedAgent.bio || '开始聊天吧！'}</div>
                </div>
              )}
              {messages.map((msg) => (
                <MessageBubble
                  key={msg.id}
                  role={msg.role}
                  content={msg.content}
                  isStreaming={msg.isStreaming}
                  agentName={msg.role === 'assistant' ? selectedAgent.name : undefined}
                  agentCode={msg.role === 'assistant' ? selectedAgent.code : undefined}
                  timestamp={msg.timestamp}
                />
              ))}
              <div ref={messagesEndRef} />
            </div>

            {/* 输入区 */}
            <div className="px-4 py-3 bg-white border-t border-gray-200">
              <div className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`发消息给 ${selectedAgent.name}...`}
                  rows={1}
                  disabled={isSending}
                  className="flex-1 resize-none rounded-2xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:border-green-400 transition-colors disabled:opacity-50 max-h-32 overflow-y-auto"
                  style={{ minHeight: '42px' }}
                  onInput={(e) => {
                    const el = e.currentTarget
                    el.style.height = 'auto'
                    el.style.height = Math.min(el.scrollHeight, 128) + 'px'
                  }}
                />
                <button
                  onClick={sendMessage}
                  disabled={!input.trim() || isSending}
                  className="w-10 h-10 rounded-full bg-green-500 text-white flex items-center justify-center flex-shrink-0 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Send size={18} />
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-1 px-1">Enter 发送 · Shift+Enter 换行</p>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <MessageCircle size={48} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">选择一个 Agent 开始聊天</p>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
