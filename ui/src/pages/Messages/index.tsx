// pages/Messages/index.tsx - 消息页（私聊 + 群聊统一）
import { useState, useEffect, useRef, useCallback } from 'react'
import {
  Send, MessageCircle, Trash2, Users, Settings,
  Plus, X, Crown, Shield, Ban, UserMinus, ChevronRight,
} from 'lucide-react'
import { api, filterThink } from '../../api/client'
import type { AgentSummary } from '../../api/client'
import MessageBubble from '../../components/MessageBubble'
import AvatarBubble from '../../components/AvatarBubble'

const BASE_URL = 'http://10.40.108.146:8766'

// ─────────────────────────────────────────────────────────────
// 通用类型
// ─────────────────────────────────────────────────────────────
interface PrivateMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  timestamp?: Date
  isGreeting?: boolean
}

interface SessionState {
  sessionId: string
  messages: PrivateMessage[]
}

interface GroupMemberInfo {
  agent_code: string
  role: 'owner' | 'admin' | 'member'
  muted: boolean
}

interface GroupInfo {
  group_id: string
  name: string
  description: string
  member_count?: number
  members: GroupMemberInfo[]
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

type SelectedItem =
  | { type: 'private'; agent: AgentSummary }
  | { type: 'group'; group: GroupInfo }
  | null

// ─────────────────────────────────────────────────────────────
// 群聊子组件
// ─────────────────────────────────────────────────────────────
function RoleBadge({ role, muted }: { role: string; muted: boolean }) {
  if (muted) return <span className="text-xs bg-red-100 text-red-500 px-1.5 py-0.5 rounded-full">禁言</span>
  if (role === 'owner') return <span className="text-xs bg-yellow-100 text-yellow-600 px-1.5 py-0.5 rounded-full flex items-center gap-0.5"><Crown size={10} />群主</span>
  if (role === 'admin') return <span className="text-xs bg-blue-100 text-blue-500 px-1.5 py-0.5 rounded-full flex items-center gap-0.5"><Shield size={10} />管理员</span>
  return null
}

function CreateGroupModal({
  agents,
  onClose,
  onCreated,
}: {
  agents: AgentInfo[]
  onClose: () => void
  onCreated: (group: GroupInfo) => void
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [memberRoles, setMemberRoles] = useState<Record<string, 'owner' | 'admin' | 'member'>>({})
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const selectedCodes = Object.keys(memberRoles)

  const toggleAgent = (code: string) => {
    setMemberRoles(prev => {
      const next = { ...prev }
      if (next[code]) {
        delete next[code]
        const remaining = Object.keys(next)
        if (remaining.length > 0 && !Object.values(next).includes('owner')) {
          next[remaining[0]] = 'owner'
        }
      } else {
        const hasOwner = Object.values(next).includes('owner')
        next[code] = hasOwner ? 'member' : 'owner'
      }
      return next
    })
  }

  const setRole = (code: string, role: 'owner' | 'admin' | 'member') => {
    setMemberRoles(prev => {
      const next = { ...prev }
      if (role === 'owner') {
        for (const k of Object.keys(next)) {
          if (next[k] === 'owner') next[k] = 'admin'
        }
      }
      next[code] = role
      return next
    })
  }

  const handleCreate = async () => {
    if (!name.trim()) { setError('请输入群名称'); return }
    if (selectedCodes.length === 0) { setError('请至少选择一个成员'); return }
    if (!Object.values(memberRoles).includes('owner')) { setError('请指定一个群主'); return }
    setCreating(true)
    try {
      const members = selectedCodes.map(code => ({ agent_code: code, role: memberRoles[code] }))
      const res = await fetch(`${BASE_URL}/api/groups`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name.trim(), description: description.trim(), members }),
      })
      const data = await res.json()
      if (data.ok) {
        const detailRes = await fetch(`${BASE_URL}/api/groups/${data.group_id}`)
        const group = await detailRes.json()
        onCreated(group)
      } else {
        setError('创建失败，请重试')
      }
    } catch {
      setError('网络错误')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full max-w-md shadow-xl" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-800">创建群聊</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
        </div>
        <div className="p-4 space-y-4 max-h-[70vh] overflow-y-auto">
          <div>
            <label className="text-sm text-gray-600 mb-1 block">群名称 *</label>
            <input value={name} onChange={e => setName(e.target.value)} placeholder="给这个群起个名字..."
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400" />
          </div>
          <div>
            <label className="text-sm text-gray-600 mb-1 block">群描述</label>
            <input value={description} onChange={e => setDescription(e.target.value)} placeholder="简单介绍一下这个群..."
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400" />
          </div>
          <div>
            <label className="text-sm text-gray-600 mb-2 block">选择成员</label>
            <div className="space-y-2">
              {agents.map(agent => {
                const isSelected = !!memberRoles[agent.code]
                const role = memberRoles[agent.code]
                return (
                  <div key={agent.code}
                    className={`flex items-center gap-3 p-2.5 rounded-xl border transition-colors cursor-pointer ${isSelected ? 'border-green-400 bg-green-50' : 'border-gray-200 hover:bg-gray-50'}`}
                    onClick={() => toggleAgent(agent.code)}>
                    <AvatarBubble name={agent.name} code={agent.code} size="sm" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-800">{agent.name}</div>
                      <div className="text-xs text-gray-400 truncate">{agent.bio || agent.mode}</div>
                    </div>
                    {isSelected && (
                      <select value={role}
                        onChange={e => { e.stopPropagation(); setRole(agent.code, e.target.value as 'owner' | 'admin' | 'member') }}
                        onClick={e => e.stopPropagation()}
                        className="text-xs border border-gray-300 rounded-lg px-2 py-1 bg-white focus:outline-none">
                        <option value="owner">群主</option>
                        <option value="admin">管理员</option>
                        <option value="member">成员</option>
                      </select>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
          {error && <p className="text-sm text-red-500">{error}</p>}
        </div>
        <div className="p-4 border-t border-gray-100">
          <button onClick={handleCreate} disabled={creating}
            className="w-full bg-green-500 text-white rounded-xl py-2.5 text-sm font-medium hover:bg-green-600 disabled:opacity-50 transition-colors">
            {creating ? '创建中...' : `创建群聊（${selectedCodes.length} 个成员）`}
          </button>
        </div>
      </div>
    </div>
  )
}

function GroupSettingsDrawer({
  group, agents, onClose, onGroupUpdated, onGroupDeleted,
}: {
  group: GroupInfo
  agents: AgentInfo[]
  onClose: () => void
  onGroupUpdated: (group: GroupInfo) => void
  onGroupDeleted: () => void
}) {
  const [editingName, setEditingName] = useState(false)
  const [nameInput, setNameInput] = useState(group.name)
  const [descInput, setDescInput] = useState(group.description)
  const [showAddMember, setShowAddMember] = useState(false)
  const [localGroup, setLocalGroup] = useState(group)

  useEffect(() => {
    setLocalGroup(group)
    setNameInput(group.name)
    setDescInput(group.description)
  }, [group])

  const refreshGroup = async () => {
    const res = await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}`)
    const g: GroupInfo = await res.json()
    setLocalGroup(g)
    onGroupUpdated(g)
  }

  const saveInfo = async () => {
    await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/info`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nameInput, description: descInput }),
    })
    setEditingName(false)
    await refreshGroup()
  }

  const setRole = async (agentCode: string, role: string) => {
    await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/members/${agentCode}/role`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    })
    await refreshGroup()
  }

  const toggleMute = async (agentCode: string, currentlyMuted: boolean) => {
    const method = currentlyMuted ? 'DELETE' : 'POST'
    await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/members/${agentCode}/mute`, { method })
    await refreshGroup()
  }

  const kickMember = async (agentCode: string) => {
    if (!confirm('确认踢出该成员？')) return
    await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/members/${agentCode}`, { method: 'DELETE' })
    await refreshGroup()
  }

  const dissolveGroup = async () => {
    if (!confirm(`确认解散"${localGroup.name}"？此操作不可恢复。`)) return
    await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}`, { method: 'DELETE' })
    onGroupDeleted()
  }

  const addMember = async (agentCode: string) => {
    await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/members`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agent_code: agentCode, role: 'member' }),
    })
    setShowAddMember(false)
    await refreshGroup()
  }

  const existingCodes = new Set(localGroup.members.map(m => m.agent_code))
  const availableAgents = agents.filter(a => !existingCodes.has(a.code))

  return (
    <div className="absolute top-0 right-0 h-full w-80 bg-white border-l border-gray-200 shadow-lg flex flex-col z-20 overflow-hidden">
      <div className="flex items-center justify-between p-4 border-b border-gray-100">
        <h3 className="font-semibold text-gray-800">群设置</h3>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
      </div>
      <div className="flex-1 overflow-y-auto">
        <section className="p-4 border-b border-gray-100">
          <div className="text-xs text-gray-400 mb-2 uppercase tracking-wide">基本信息</div>
          <div className="space-y-2">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">群名称</label>
              {editingName ? (
                <div className="flex gap-2">
                  <input value={nameInput} onChange={e => setNameInput(e.target.value)}
                    className="flex-1 border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-green-400" />
                  <button onClick={saveInfo} className="text-xs bg-green-500 text-white px-2 py-1 rounded-lg">保存</button>
                  <button onClick={() => setEditingName(false)} className="text-xs text-gray-400 px-2 py-1">取消</button>
                </div>
              ) : (
                <div className="text-sm text-gray-800 py-1 px-2 rounded-lg hover:bg-gray-50 cursor-pointer flex items-center justify-between"
                  onClick={() => setEditingName(true)}>
                  {localGroup.name}
                  <ChevronRight size={14} className="text-gray-400" />
                </div>
              )}
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">群描述</label>
              <textarea value={descInput} onChange={e => setDescInput(e.target.value)} onBlur={saveInfo} rows={2}
                placeholder="添加群描述..."
                className="w-full border border-gray-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-green-400 resize-none" />
            </div>
          </div>
        </section>
        <section className="p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs text-gray-400 uppercase tracking-wide">成员（{localGroup.members.length}）</div>
            {availableAgents.length > 0 && (
              <button onClick={() => setShowAddMember(v => !v)}
                className="text-xs text-green-500 hover:text-green-600 flex items-center gap-1">
                <Plus size={12} /> 添加成员
              </button>
            )}
          </div>
          {showAddMember && availableAgents.length > 0 && (
            <div className="mb-3 border border-gray-200 rounded-xl overflow-hidden">
              {availableAgents.map(agent => (
                <button key={agent.code} onClick={() => addMember(agent.code)}
                  className="w-full flex items-center gap-2 p-2.5 hover:bg-gray-50 text-left border-b border-gray-100 last:border-0">
                  <AvatarBubble name={agent.name} code={agent.code} size="sm" />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium text-gray-800">{agent.name}</div>
                    <div className="text-xs text-gray-400 truncate">{agent.bio || agent.mode}</div>
                  </div>
                  <Plus size={14} className="text-green-500 flex-shrink-0" />
                </button>
              ))}
            </div>
          )}
          <div className="space-y-1">
            {localGroup.members.map(member => {
              const agentInfo = agents.find(a => a.code === member.agent_code)
              const name = agentInfo?.name || member.agent_code
              return (
                <div key={member.agent_code} className="flex items-center gap-2 p-2 rounded-xl hover:bg-gray-50">
                  <AvatarBubble name={name} code={member.agent_code} size="sm" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-medium text-gray-800 truncate">{name}</span>
                      <RoleBadge role={member.role} muted={member.muted} />
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    {member.role !== 'owner' && (
                      <button onClick={() => toggleMute(member.agent_code, member.muted)}
                        className={`p-1 rounded-lg transition-colors ${member.muted ? 'text-red-400 hover:bg-red-50' : 'text-gray-400 hover:bg-gray-100'}`}
                        title={member.muted ? '解除禁言' : '禁言'}>
                        <Ban size={14} />
                      </button>
                    )}
                    {member.role !== 'owner' && (
                      <select value={member.role} onChange={e => setRole(member.agent_code, e.target.value)}
                        className="text-xs border border-gray-200 rounded-lg px-1.5 py-1 bg-white focus:outline-none text-gray-600">
                        <option value="admin">管理员</option>
                        <option value="member">成员</option>
                      </select>
                    )}
                    {member.role !== 'owner' && (
                      <button onClick={() => kickMember(member.agent_code)}
                        className="p-1 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors" title="踢出成员">
                        <UserMinus size={14} />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>
        <section className="p-4 border-t border-gray-100">
          <button onClick={dissolveGroup}
            className="w-full text-center text-sm text-red-500 hover:text-red-600 py-2 rounded-xl hover:bg-red-50 transition-colors">
            解散群聊
          </button>
        </section>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────
// 主页面
// ─────────────────────────────────────────────────────────────
export default function MessagesPage() {
  // ── 会话列表状态 ───────────────────────────────────────────
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [allAgentsInfo, setAllAgentsInfo] = useState<AgentInfo[]>([])
  const [agentMap, setAgentMap] = useState<Record<string, AgentInfo>>({})
  const [loadingList, setLoadingList] = useState(true)
  const [selected, setSelected] = useState<SelectedItem>(null)
  const [showCreateModal, setShowCreateModal] = useState(false)

  // ── 私聊状态 ──────────────────────────────────────────────
  const [sessions, setSessions] = useState<Record<string, SessionState>>(() => {
    try {
      const saved = localStorage.getItem('haji_sessions')
      if (saved) {
        const parsed = JSON.parse(saved)
        Object.values(parsed).forEach((session: unknown) => {
          const s = session as SessionState
          s.messages = s.messages.map((m) => ({
            ...m,
            timestamp: m.timestamp ? new Date(m.timestamp as unknown as string) : undefined,
          }))
        })
        return parsed
      }
    } catch { /* ignore */ }
    return {}
  })
  const [privateInput, setPrivateInput] = useState('')
  const [isSendingPrivate, setIsSendingPrivate] = useState(false)
  const privateEndRef = useRef<HTMLDivElement>(null)

  // ── 群聊状态 ──────────────────────────────────────────────
  const [groupMessages, setGroupMessages] = useState<GroupMessage[]>([])
  const [groupInput, setGroupInput] = useState('')
  const [isSendingGroup, setIsSendingGroup] = useState(false)
  const [speakingAgents, setSpeakingAgents] = useState<string[]>([])
  const [showSettings, setShowSettings] = useState(false)
  const groupEndRef = useRef<HTMLDivElement>(null)

  // ── 初始化拉取数据 ────────────────────────────────────────
  useEffect(() => {
    Promise.all([
      api.getAgents().catch(() => [] as AgentSummary[]),
      fetch(`${BASE_URL}/api/groups`).then(r => r.json()).catch(() => [] as GroupInfo[]),
    ]).then(([agentsData, groupsData]) => {
      setAgents(agentsData)
      setGroups(groupsData)
      setAllAgentsInfo(agentsData as AgentInfo[])
      const map: Record<string, AgentInfo> = {}
      ;(agentsData as AgentInfo[]).forEach(a => { map[a.code] = a })
      setAgentMap(map)
      setLoadingList(false)
      // 默认选中第一个
      if (agentsData.length > 0) {
        setSelected({ type: 'private', agent: agentsData[0] })
      } else if (groupsData.length > 0) {
        selectGroup(groupsData[0])
      }
    })
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── 持久化 sessions ───────────────────────────────────────
  useEffect(() => {
    try {
      const toSave: Record<string, SessionState> = {}
      for (const [code, session] of Object.entries(sessions)) {
        toSave[code] = { ...session, messages: session.messages.filter(m => !m.isGreeting) }
      }
      localStorage.setItem('haji_sessions', JSON.stringify(toSave))
    } catch { /* ignore */ }
  }, [sessions])

  // ── 切换私聊时拉欢迎语 ────────────────────────────────────
  useEffect(() => {
    if (selected?.type !== 'private') return
    const agent = selected.agent
    const session = sessions[agent.code]
    const realMessages = (session?.messages ?? []).filter(m => !m.isGreeting)
    if (realMessages.length > 0) return
    const agentCode = agent.code
    fetch(`${BASE_URL}/api/agents/${agentCode}/greeting?user_id=user_001`)
      .then(r => r.json())
      .then(data => {
        if (!data.greeting) return
        setSessions(prev => {
          const existing = prev[agentCode]
          const currentReal = (existing?.messages ?? []).filter(m => !m.isGreeting)
          if (currentReal.length > 0) return prev
          return {
            ...prev,
            [agentCode]: {
              sessionId: existing?.sessionId ?? '',
              messages: [{
                id: `greeting_${agentCode}`,
                role: 'assistant' as const,
                content: data.greeting,
                timestamp: new Date(),
                isGreeting: true,
              }],
            },
          }
        })
      })
      .catch(() => {})
  }, [selected]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── 滚动 ─────────────────────────────────────────────────
  useEffect(() => {
    privateEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [sessions, selected])

  useEffect(() => {
    groupEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [groupMessages])

  // ── 选择群聊 ─────────────────────────────────────────────
  const selectGroup = useCallback(async (group: GroupInfo) => {
    setSelected({ type: 'group', group })
    setGroupMessages([])
    setShowSettings(false)
    try {
      const res = await fetch(`${BASE_URL}/api/groups/${group.group_id}/messages?limit=50`)
      if (!res.ok) return
      const data: Array<{
        type: string; agent_code: string; agent_name: string
        content: string; user_id: string; timestamp: string
      }> = await res.json()
      if (!Array.isArray(data) || data.length === 0) return
      const restored: GroupMessage[] = data
        .filter(m => m.content)
        .map((m, i) => ({
          id: `hist_${i}_${m.timestamp || i}`,
          type: m.type as 'user' | 'agent' | 'system',
          agent_code: m.agent_code || undefined,
          agent_name: m.agent_name || undefined,
          content: m.content,
          timestamp: m.timestamp ? new Date(m.timestamp) : new Date(),
        }))
      setGroupMessages(restored)
    } catch { /* 静默 */ }
  }, [])

  // ── 发送私聊 ─────────────────────────────────────────────
  const sendPrivateMessage = useCallback(() => {
    if (selected?.type !== 'private') return
    if (!privateInput.trim() || isSendingPrivate) return
    const userText = privateInput.trim()
    setPrivateInput('')
    setIsSendingPrivate(true)
    const agentCode = selected.agent.code
    const sessionId = sessions[agentCode]?.sessionId || ''
    const userMsgId = Date.now().toString()
    const aiMsgId = (Date.now() + 1).toString()

    setSessions(prev => {
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

    api.chatStream(
      agentCode, userText, sessionId,
      (token) => {
        setSessions(prev => {
          const session = prev[agentCode]
          if (!session) return prev
          return {
            ...prev,
            [agentCode]: {
              ...session,
              messages: session.messages.map(m =>
                m.id === aiMsgId ? { ...m, content: m.content + token } : m,
              ),
            },
          }
        })
      },
      (finalContent, newSessionId) => {
        setSessions(prev => {
          const session = prev[agentCode]
          if (!session) return prev
          return {
            ...prev,
            [agentCode]: {
              sessionId: newSessionId || session.sessionId,
              messages: session.messages.map(m =>
                m.id === aiMsgId
                  ? { ...m, content: filterThink(finalContent) || m.content, isStreaming: false }
                  : m,
              ),
            },
          }
        })
        setIsSendingPrivate(false)
      },
      (err) => {
        setSessions(prev => {
          const session = prev[agentCode]
          if (!session) return prev
          return {
            ...prev,
            [agentCode]: {
              ...session,
              messages: session.messages.map(m =>
                m.id === aiMsgId ? { ...m, content: `[错误] ${err}`, isStreaming: false } : m,
              ),
            },
          }
        })
        setIsSendingPrivate(false)
      },
    )
  }, [privateInput, selected, isSendingPrivate, sessions])

  // ── 发送群聊消息 ─────────────────────────────────────────
  const sendGroupMessage = async () => {
    if (selected?.type !== 'group') return
    if (!groupInput.trim() || isSendingGroup) return
    const text = groupInput.trim()
    const group = selected.group
    setGroupInput('')
    setIsSendingGroup(true)

    setGroupMessages(prev => [...prev, {
      id: Date.now().toString(), type: 'user', content: text, timestamp: new Date(),
    }])

    try {
      const res = await fetch(`${BASE_URL}/api/groups/${group.group_id}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_id: group.group_id, message: text, user_id: 'user_001' }),
      })
      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
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
              const msgId = `${event.agent_code}_${Date.now()}`
              streamingIds[event.agent_code] = msgId
              setGroupMessages(prev => [...prev, {
                id: msgId, type: 'agent',
                agent_code: event.agent_code,
                agent_name: event.agent_name || agentMap[event.agent_code]?.name || event.agent_code,
                content: '', isStreaming: true, timestamp: new Date(),
              }])
            } else if (event.type === 'token') {
              const msgId = streamingIds[event.agent_code]
              if (msgId) setGroupMessages(prev => prev.map(m =>
                m.id === msgId ? { ...m, content: m.content + event.content } : m,
              ))
            } else if (event.type === 'agent_done') {
              const msgId = streamingIds[event.agent_code]
              const clean = event.content.replace(/<think>[\s\S]*?<\/think>/g, '').trim()
              if (msgId) setGroupMessages(prev => prev.map(m =>
                m.id === msgId ? { ...m, content: clean, isStreaming: false } : m,
              ))
              delete streamingIds[event.agent_code]
            } else if (event.type === 'group_done') {
              setSpeakingAgents([])
            } else if (event.type === 'system') {
              setGroupMessages(prev => [...prev, {
                id: Date.now().toString(), type: 'system', content: event.content, timestamp: new Date(),
              }])
            }
          } catch { /* ignore */ }
        }
      }
    } catch (e) {
      console.error(e)
    } finally {
      setIsSendingGroup(false)
      setSpeakingAgents([])
    }
  }

  // ── 群组操作回调 ─────────────────────────────────────────
  const loadGroups = async () => {
    const res = await fetch(`${BASE_URL}/api/groups`)
    const gs: GroupInfo[] = await res.json()
    setGroups(gs)
    return gs
  }

  const handleGroupCreated = async (group: GroupInfo) => {
    setShowCreateModal(false)
    const gs = await loadGroups()
    const fresh = gs.find(g => g.group_id === group.group_id)
    if (fresh) await selectGroup(fresh)
  }

  const handleGroupUpdated = (updated: GroupInfo) => {
    setGroups(prev => prev.map(g => g.group_id === updated.group_id ? updated : g))
    setSelected({ type: 'group', group: updated })
  }

  const handleGroupDeleted = async () => {
    setShowSettings(false)
    const gs = await loadGroups()
    if (gs.length > 0) {
      await selectGroup(gs[0])
    } else {
      setSelected(agents.length > 0 ? { type: 'private', agent: agents[0] } : null)
    }
  }

  // ── 渲染 ─────────────────────────────────────────────────
  const currentPrivateMessages = selected?.type === 'private'
    ? (sessions[selected.agent.code]?.messages ?? [])
    : []

  const currentGroup = selected?.type === 'group' ? selected.group : null

  return (
    <div className="flex h-full bg-gray-100 relative overflow-hidden">
      {/* ── 左侧统一会话列表 ── */}
      <aside className="w-20 md:w-64 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
        <div className="p-3 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700 hidden md:block">消息</h2>
          <button
            onClick={() => setShowCreateModal(true)}
            className="w-7 h-7 rounded-lg bg-green-500 text-white flex items-center justify-center hover:bg-green-600 transition-colors flex-shrink-0"
            title="创建群聊"
          >
            <Plus size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loadingList && <div className="p-4 text-center text-gray-400 text-xs">加载中...</div>}

          {/* 私聊列表 */}
          {agents.map(agent => {
            const isSelected = selected?.type === 'private' && selected.agent.code === agent.code
            const agentMessages = sessions[agent.code]?.messages ?? []
            const lastMsg = agentMessages[agentMessages.length - 1]
            return (
              <button
                key={agent.code}
                onClick={() => setSelected({ type: 'private', agent })}
                className={`w-full flex items-center gap-3 px-3 py-3 hover:bg-gray-50 transition-colors ${isSelected ? 'bg-gray-100' : ''}`}
              >
                <AvatarBubble name={agent.name} code={agent.code} size="md" />
                <div className="flex-1 text-left min-w-0 hidden md:block">
                  <div className="text-sm font-medium text-gray-800 truncate">{agent.name}</div>
                  <div className="text-xs text-gray-400 truncate">
                    {lastMsg
                      ? (lastMsg.role === 'user' ? `我: ${lastMsg.content}` : lastMsg.content)
                      : agent.bio || '点击开始聊天'}
                  </div>
                </div>
              </button>
            )
          })}

          {/* 群聊列表 */}
          {groups.map(group => {
            const isSelected = selected?.type === 'group' && selected.group.group_id === group.group_id
            return (
              <button
                key={group.group_id}
                onClick={() => selectGroup(group)}
                className={`w-full flex items-center gap-3 px-3 py-3 hover:bg-gray-50 transition-colors ${isSelected ? 'bg-gray-100' : ''}`}
              >
                <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-green-400 to-emerald-600 flex items-center justify-center text-white font-bold flex-shrink-0 text-sm">
                  {group.name[0]}
                </div>
                <div className="flex-1 text-left min-w-0 hidden md:block">
                  <div className="text-sm font-medium text-gray-800 truncate">{group.name}</div>
                  <div className="text-xs text-gray-400">{group.member_count ?? group.members.length} 个成员</div>
                </div>
              </button>
            )
          })}

          {!loadingList && agents.length === 0 && groups.length === 0 && (
            <div className="p-4 text-center text-gray-400 text-xs">暂无会话</div>
          )}
        </div>
      </aside>

      {/* ── 右侧聊天区 ── */}
      <main className="flex-1 flex flex-col min-w-0 relative">
        {/* 私聊窗口 */}
        {selected?.type === 'private' && (
          <>
            <header className="flex items-center gap-3 px-4 py-3 bg-white border-b border-gray-200">
              <AvatarBubble name={selected.agent.name} code={selected.agent.code} size="sm" />
              <div>
                <div className="font-semibold text-gray-800">{selected.agent.name}</div>
                <div className="text-xs text-gray-400">{selected.agent.bio}</div>
              </div>
              <button
                onClick={() => {
                  if (selected?.type !== 'private') return
                  setSessions(prev => { const next = { ...prev }; delete next[selected.agent.code]; return next })
                }}
                className="ml-auto p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600 transition-colors"
                title="清除聊天记录"
              >
                <Trash2 size={16} />
              </button>
            </header>

            <div className="flex-1 overflow-y-auto px-4 py-4">
              {currentPrivateMessages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-gray-400">
                  <AvatarBubble name={selected.agent.name} code={selected.agent.code} size="xl" className="mb-3" />
                  <div className="text-sm font-medium text-gray-600">{selected.agent.name}</div>
                  <div className="text-xs mt-1">{selected.agent.bio || '开始聊天吧！'}</div>
                </div>
              )}
              {currentPrivateMessages.map(msg => (
                <MessageBubble
                  key={msg.id}
                  role={msg.role}
                  content={msg.content}
                  isStreaming={msg.isStreaming}
                  agentName={msg.role === 'assistant' ? selected.agent.name : undefined}
                  agentCode={msg.role === 'assistant' ? selected.agent.code : undefined}
                  timestamp={msg.timestamp}
                />
              ))}
              <div ref={privateEndRef} />
            </div>

            <div className="px-4 py-3 bg-white border-t border-gray-200">
              <div className="flex items-end gap-2">
                <textarea
                  value={privateInput}
                  onChange={e => setPrivateInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendPrivateMessage() } }}
                  placeholder={`发消息给 ${selected.agent.name}...`}
                  rows={1}
                  disabled={isSendingPrivate}
                  className="flex-1 resize-none rounded-2xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:border-green-400 transition-colors disabled:opacity-50 max-h-32 overflow-y-auto"
                  style={{ minHeight: '42px' }}
                  onInput={e => { const el = e.currentTarget; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 128) + 'px' }}
                />
                <button
                  onClick={sendPrivateMessage}
                  disabled={!privateInput.trim() || isSendingPrivate}
                  className="w-10 h-10 rounded-full bg-green-500 text-white flex items-center justify-center flex-shrink-0 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Send size={18} />
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-1 px-1">Enter 发送 · Shift+Enter 换行</p>
            </div>
          </>
        )}

        {/* 群聊窗口 */}
        {selected?.type === 'group' && currentGroup && (
          <>
            <header className="flex items-center gap-3 px-4 py-3 bg-white border-b border-gray-200 z-10">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-green-400 to-emerald-600 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
                {currentGroup.name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-gray-800 truncate">{currentGroup.name}</div>
                <div className="text-xs text-gray-400">{currentGroup.members.length} 个 AI 成员</div>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex -space-x-2">
                  {currentGroup.members.slice(0, 3).map(m => (
                    <AvatarBubble key={m.agent_code} name={agentMap[m.agent_code]?.name || m.agent_code} code={m.agent_code} size="sm" className="border-2 border-white" />
                  ))}
                </div>
                <button
                  onClick={() => setShowSettings(v => !v)}
                  className={`p-2 rounded-xl transition-colors ${showSettings ? 'bg-gray-100 text-gray-700' : 'text-gray-400 hover:bg-gray-50 hover:text-gray-600'}`}
                >
                  <Settings size={18} />
                </button>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
              {groupMessages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-gray-400">
                  <Users size={48} className="mb-3 opacity-30" />
                  <p className="text-sm">向群里发一条消息，看看 AI 们怎么回应</p>
                  <p className="text-xs mt-1 text-gray-300">@名字 指定成员 · @all 呼叫所有人</p>
                </div>
              )}
              {groupMessages.map(msg => {
                if (msg.type === 'system') return (
                  <div key={msg.id} className="flex justify-center">
                    <span className="text-xs text-gray-400 bg-gray-100 px-3 py-1 rounded-full">{msg.content}</span>
                  </div>
                )
                const isUser = msg.type === 'user'
                return (
                  <div key={msg.id} className={`flex items-end gap-2 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
                    {isUser ? (
                      <div className="w-8 h-8 rounded-full bg-green-500 flex items-center justify-center text-white text-xs font-bold flex-shrink-0">我</div>
                    ) : (
                      <AvatarBubble name={msg.agent_name || msg.agent_code || '?'} code={msg.agent_code || 'default'} size="sm" />
                    )}
                    <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-[70%]`}>
                      {!isUser && msg.agent_name && (
                        <span className="text-xs text-gray-500 mb-1 px-1">{msg.agent_name}</span>
                      )}
                      <div className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed break-words whitespace-pre-wrap ${isUser ? 'bg-green-500 text-white rounded-br-sm' : 'bg-white text-gray-800 shadow-sm rounded-bl-sm'}`}>
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
              {speakingAgents.length > 0 && (
                <div className="flex items-center gap-1 text-xs text-gray-400 px-1">
                  <span className="animate-pulse">●</span>
                  {speakingAgents.map(code => agentMap[code]?.name || code).join('、')} 正在回复...
                </div>
              )}
              <div ref={groupEndRef} />
            </div>

            <div className="px-4 py-3 bg-white border-t border-gray-200">
              <div className="flex items-end gap-2">
                <textarea
                  value={groupInput}
                  onChange={e => setGroupInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendGroupMessage() } }}
                  placeholder={`发消息到 ${currentGroup.name}...`}
                  rows={1}
                  disabled={isSendingGroup}
                  className="flex-1 resize-none rounded-2xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:border-green-400 transition-colors disabled:opacity-50 max-h-32"
                  style={{ minHeight: '42px' }}
                  onInput={e => { const el = e.currentTarget; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 128) + 'px' }}
                />
                <button
                  onClick={sendGroupMessage}
                  disabled={!groupInput.trim() || isSendingGroup}
                  className="w-10 h-10 rounded-full bg-green-500 text-white flex items-center justify-center flex-shrink-0 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Send size={18} />
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-1 px-1">Enter 发送 · Shift+Enter 换行 · @名字 指定成员 · @all 全员</p>
            </div>

            {showSettings && currentGroup && (
              <GroupSettingsDrawer
                group={currentGroup}
                agents={allAgentsInfo}
                onClose={() => setShowSettings(false)}
                onGroupUpdated={handleGroupUpdated}
                onGroupDeleted={handleGroupDeleted}
              />
            )}
          </>
        )}

        {/* 空状态 */}
        {!selected && (
          <div className="flex-1 flex items-center justify-center text-gray-400">
            <div className="text-center">
              <MessageCircle size={48} className="mx-auto mb-3 opacity-30" />
              <p className="text-sm">选择一个会话开始聊天</p>
            </div>
          </div>
        )}
      </main>

      {/* 建群 Modal */}
      {showCreateModal && (
        <CreateGroupModal
          agents={allAgentsInfo}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleGroupCreated}
        />
      )}
    </div>
  )
}
