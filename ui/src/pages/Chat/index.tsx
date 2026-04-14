// pages/Chat/index.tsx - 会话页（微信风格）
import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, MessageCircle } from 'lucide-react'
import { api } from '../../api/client'
import type { AgentSummary } from '../../api/client'
import MessageBubble from '../../components/MessageBubble'

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
}

interface SessionState {
  sessionId: string
  messages: Message[]
}

export default function ChatPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [selectedAgent, setSelectedAgent] = useState<AgentSummary | null>(null)
  const [sessions, setSessions] = useState<Record<string, SessionState>>({})
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
            { id: userMsgId, role: 'user', content: userText },
            { id: aiMsgId, role: 'assistant', content: '', isStreaming: true },
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
                <div className="w-10 h-10 rounded-full bg-gray-200 flex items-center justify-center text-xl flex-shrink-0">
                  {agent.avatar || '🤖'}
                </div>
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
              <div className="text-2xl">{selectedAgent.avatar || '🤖'}</div>
              <div>
                <div className="font-semibold text-gray-800">{selectedAgent.name}</div>
                <div className="text-xs text-gray-400">{selectedAgent.bio}</div>
              </div>
            </header>

            {/* 消息区 */}
            <div className="flex-1 overflow-y-auto px-4 py-4">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-gray-400">
                  <div className="text-5xl mb-3">{selectedAgent.avatar || '🤖'}</div>
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
                  agentAvatar={msg.role === 'assistant' ? selectedAgent.avatar : undefined}
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
