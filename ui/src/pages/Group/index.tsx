// pages/Group/index.tsx - 群聊页面
import { useState, useEffect, useRef } from 'react'
import { Send, Users } from 'lucide-react'
import AvatarBubble from '../../components/AvatarBubble'

interface GroupInfo {
  group_id: string
  name: string
  description: string
  member_count?: number
  members: { agent_code: string; role: string }[]
}

interface AgentInfo {
  code: string
  name: string
  bio: string
  tags: string[]
  mode: string
}

interface GroupMessage {
  id: string
  type: 'user' | 'agent' | 'system'
  agent_code?: string
  agent_name?: string
  content: string
  isStreaming?: boolean
  timestamp: Date
}

const BASE_URL = 'http://localhost:8766'

export default function GroupPage() {
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [selectedGroup, setSelectedGroup] = useState<GroupInfo | null>(null)
  const [agentMap, setAgentMap] = useState<Record<string, AgentInfo>>({})
  const [messages, setMessages] = useState<GroupMessage[]>([])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [speakingAgents, setSpeakingAgents] = useState<string[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    // 加载群组列表
    fetch(`${BASE_URL}/api/groups`)
      .then(r => r.json())
      .then(setGroups)
      .catch(console.error)
    // 加载 Agent 信息
    fetch(`${BASE_URL}/api/agents`)
      .then(r => r.json())
      .then((agents: AgentInfo[]) => {
        const map: Record<string, AgentInfo> = {}
        agents.forEach(a => { map[a.code] = a })
        setAgentMap(map)
      })
      .catch(console.error)
  }, [])

  useEffect(() => {
    if (groups.length > 0 && !selectedGroup) {
      setSelectedGroup(groups[0])
    }
  }, [groups])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim() || !selectedGroup || isSending) return

    const text = input.trim()
    setInput('')
    setIsSending(true)

    // 添加用户消息
    const userMsg: GroupMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: text,
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])

    // 发起群聊 SSE
    try {
      const res = await fetch(`${BASE_URL}/api/groups/${selectedGroup.group_id}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          group_id: selectedGroup.group_id,
          message: text,
          user_id: 'user_001',
        }),
      })

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      // 当前流式消息的 id map
      const streamingIds: Record<string, string> = {}

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const event = JSON.parse(line.slice(6))

            if (event.type === 'speakers') {
              setSpeakingAgents(event.agent_codes)
            } else if (event.type === 'agent_start') {
              // 创建该 Agent 的流式消息占位
              const msgId = `${event.agent_code}_${Date.now()}`
              streamingIds[event.agent_code] = msgId
              const agentInfo = agentMap[event.agent_code]
              setMessages(prev => [...prev, {
                id: msgId,
                type: 'agent',
                agent_code: event.agent_code,
                agent_name: event.agent_name || agentInfo?.name || event.agent_code,
                content: '',
                isStreaming: true,
                timestamp: new Date(),
              }])
            } else if (event.type === 'token') {
              const msgId = streamingIds[event.agent_code]
              if (msgId) {
                setMessages(prev => prev.map(m =>
                  m.id === msgId ? { ...m, content: m.content + event.content } : m
                ))
              }
            } else if (event.type === 'agent_done') {
              const msgId = streamingIds[event.agent_code]
              // 过滤 think 块
              const clean = event.content.replace(/<think>[\s\S]*?<\/think>/g, '').trim()
              if (msgId) {
                setMessages(prev => prev.map(m =>
                  m.id === msgId ? { ...m, content: clean, isStreaming: false } : m
                ))
              }
              delete streamingIds[event.agent_code]
            } else if (event.type === 'group_done') {
              setSpeakingAgents([])
            } else if (event.type === 'system') {
              setMessages(prev => [...prev, {
                id: Date.now().toString(),
                type: 'system',
                content: event.content,
                timestamp: new Date(),
              }])
            }
          } catch {
            // ignore parse errors
          }
        }
      }
    } catch (e) {
      console.error(e)
    } finally {
      setIsSending(false)
      setSpeakingAgents([])
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div className="flex h-full bg-gray-100">
      {/* 左侧：群组列表 */}
      <aside className="w-16 md:w-56 bg-white border-r border-gray-200 flex flex-col">
        <div className="p-3 border-b border-gray-100">
          <h2 className="text-sm font-semibold text-gray-700 hidden md:block">群聊</h2>
        </div>
        <div className="flex-1 overflow-y-auto">
          {groups.map(group => (
            <button
              key={group.group_id}
              onClick={() => setSelectedGroup(group)}
              className={`w-full flex items-center gap-3 px-3 py-3 hover:bg-gray-50 transition-colors ${
                selectedGroup?.group_id === group.group_id ? 'bg-gray-100' : ''
              }`}
            >
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-green-400 to-emerald-600 flex items-center justify-center text-white font-bold flex-shrink-0">
                {group.name[0]}
              </div>
              <div className="flex-1 text-left min-w-0 hidden md:block">
                <div className="text-sm font-medium text-gray-800 truncate">{group.name}</div>
                <div className="text-xs text-gray-400">{group.member_count ?? group.members.length} 个成员</div>
              </div>
            </button>
          ))}
        </div>
      </aside>

      {/* 右侧：群聊窗口 */}
      <main className="flex-1 flex flex-col min-w-0">
        {selectedGroup ? (
          <>
            {/* 头部 */}
            <header className="flex items-center gap-3 px-4 py-3 bg-white border-b border-gray-200">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-green-400 to-emerald-600 flex items-center justify-center text-white font-bold text-sm">
                {selectedGroup.name[0]}
              </div>
              <div className="flex-1">
                <div className="font-semibold text-gray-800">{selectedGroup.name}</div>
                <div className="text-xs text-gray-400">{selectedGroup.members.length} 个 AI 成员</div>
              </div>
              {/* 成员头像列 */}
              <div className="flex -space-x-2">
                {selectedGroup.members.slice(0, 4).map(m => (
                  <AvatarBubble
                    key={m.agent_code}
                    name={agentMap[m.agent_code]?.name || m.agent_code}
                    code={m.agent_code}
                    size="sm"
                    className="border-2 border-white"
                  />
                ))}
              </div>
            </header>

            {/* 消息区 */}
            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-gray-400">
                  <Users size={48} className="mb-3 opacity-30" />
                  <p className="text-sm">向群里发一条消息，看看 AI 们怎么回应</p>
                  <p className="text-xs mt-1 text-gray-300">可以用 @名字 指定某个 AI 回复</p>
                </div>
              )}

              {messages.map(msg => {
                if (msg.type === 'system') {
                  return (
                    <div key={msg.id} className="flex justify-center">
                      <span className="text-xs text-gray-400 bg-gray-100 px-3 py-1 rounded-full">
                        {msg.content}
                      </span>
                    </div>
                  )
                }

                const isUser = msg.type === 'user'
                return (
                  <div key={msg.id} className={`flex items-end gap-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
                    {isUser ? (
                      <div className="w-8 h-8 rounded-full bg-green-500 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">我</div>
                    ) : (
                      <AvatarBubble
                        name={msg.agent_name || msg.agent_code || '?'}
                        code={msg.agent_code || 'default'}
                        size="sm"
                      />
                    )}
                    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-[70%]`}>
                      {!isUser && msg.agent_name && (
                        <span className="text-xs text-gray-500 mb-1 px-1">{msg.agent_name}</span>
                      )}
                      <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed break-words whitespace-pre-wrap ${
                        isUser
                          ? 'bg-green-500 text-white rounded-br-sm'
                          : 'bg-white text-gray-800 shadow-sm rounded-bl-sm'
                      }`}>
                        {msg.content || (msg.isStreaming ? '' : '...')}
                        {msg.isStreaming && <span className="animate-pulse ml-0.5">▌</span>}
                      </div>
                      <div className="text-xs text-gray-400 mt-1 px-1">
                        {msg.timestamp.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
                      </div>
                    </div>
                  </div>
                )
              })}

              {/* 正在发言提示 */}
              {speakingAgents.length > 0 && (
                <div className="flex items-center gap-1 text-xs text-gray-400 px-1">
                  <span className="animate-pulse">●</span>
                  {speakingAgents.map(code => agentMap[code]?.name || code).join('、')} 正在回复...
                </div>
              )}

              <div ref={messagesEndRef} />
            </div>

            {/* 输入区 */}
            <div className="px-4 py-3 bg-white border-t border-gray-200">
              <div className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`发消息到 ${selectedGroup.name}... （@名字 可以指定成员回复）`}
                  rows={1}
                  disabled={isSending}
                  className="flex-1 resize-none rounded-2xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:border-green-400 transition-colors disabled:opacity-50 max-h-32 overflow-y-auto"
                  style={{ minHeight: '42px' }}
                  onInput={e => {
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
              <p className="text-xs text-gray-400 mt-1 px-1">Enter 发送 · Shift+Enter 换行 · @名字 指定成员</p>
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <Users size={48} className="opacity-30" />
          </div>
        )}
      </main>
    </div>
  )
}
