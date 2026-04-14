import { useState, useEffect, useRef, useCallback } from 'react'
import { Send, Users, Settings, Plus, X, Crown, Shield, Ban, UserMinus, ChevronRight } from 'lucide-react'
import AvatarBubble from '../../components/AvatarBubble'

const BASE_URL = 'http://10.40.108.146:8766'

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

// ── 角色标签 ─────────────────────────────────────────────────
function RoleBadge({ role, muted }: { role: string; muted: boolean }) {
  if (muted) return <span className="text-xs bg-red-100 text-red-500 px-1.5 py-0.5 rounded-full">禁言</span>
  if (role === 'owner') return <span className="text-xs bg-yellow-100 text-yellow-600 px-1.5 py-0.5 rounded-full flex items-center gap-0.5"><Crown size={10} />群主</span>
  if (role === 'admin') return <span className="text-xs bg-blue-100 text-blue-500 px-1.5 py-0.5 rounded-full flex items-center gap-0.5"><Shield size={10} />管理员</span>
  return null
}

// ── 建群 Modal ────────────────────────────────────────────────
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
        // 如果删掉的是 owner，把第一个剩余的设为 owner
        const remaining = Object.keys(next)
        if (remaining.length > 0 && !Object.values(next).includes('owner')) {
          next[remaining[0]] = 'owner'
        }
      } else {
        // 第一个选的默认 owner，后续默认 member
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
        // 先把其他 owner 降为 admin
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
        // 拉取创建好的群详情
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
            <input
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="给这个群起个名字..."
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400"
            />
          </div>
          <div>
            <label className="text-sm text-gray-600 mb-1 block">群描述</label>
            <input
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="简单介绍一下这个群..."
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:border-green-400"
            />
          </div>
          <div>
            <label className="text-sm text-gray-600 mb-2 block">选择成员（点击选中，已选的可设置角色）</label>
            <div className="space-y-2">
              {agents.map(agent => {
                const isSelected = !!memberRoles[agent.code]
                const role = memberRoles[agent.code]
                return (
                  <div
                    key={agent.code}
                    className={`flex items-center gap-3 p-2.5 rounded-xl border transition-colors cursor-pointer ${
                      isSelected ? 'border-green-400 bg-green-50' : 'border-gray-200 hover:bg-gray-50'
                    }`}
                    onClick={() => toggleAgent(agent.code)}
                  >
                    <AvatarBubble name={agent.name} code={agent.code} size="sm" />
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium text-gray-800">{agent.name}</div>
                      <div className="text-xs text-gray-400 truncate">{agent.bio || agent.mode}</div>
                    </div>
                    {isSelected && (
                      <select
                        value={role}
                        onChange={e => { e.stopPropagation(); setRole(agent.code, e.target.value as 'owner' | 'admin' | 'member') }}
                        onClick={e => e.stopPropagation()}
                        className="text-xs border border-gray-300 rounded-lg px-2 py-1 bg-white focus:outline-none"
                      >
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
          <button
            onClick={handleCreate}
            disabled={creating}
            className="w-full bg-green-500 text-white rounded-xl py-2.5 text-sm font-medium hover:bg-green-600 disabled:opacity-50 transition-colors"
          >
            {creating ? '创建中...' : `创建群聊（${selectedCodes.length} 个成员）`}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── 群设置抽屉 ────────────────────────────────────────────────
function GroupSettingsDrawer({
  group,
  agents,
  onClose,
  onGroupUpdated,
  onGroupDeleted,
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

  // 同步 group prop 变化
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
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: nameInput, description: descInput }),
    })
    setEditingName(false)
    await refreshGroup()
  }

  const setRole = async (agentCode: string, role: string) => {
    await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/members/${agentCode}/role`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role }),
    })
    await refreshGroup()
  }

  const toggleMute = async (agentCode: string, currentlyMuted: boolean) => {
    if (currentlyMuted) {
      await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/members/${agentCode}/mute`, { method: 'DELETE' })
    } else {
      await fetch(`${BASE_URL}/api/groups/${localGroup.group_id}/members/${agentCode}/mute`, { method: 'POST' })
    }
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
        {/* 群信息 */}
        <section className="p-4 border-b border-gray-100">
          <div className="text-xs text-gray-400 mb-2 uppercase tracking-wide">基本信息</div>
          <div className="space-y-2">
            <div>
              <label className="text-xs text-gray-500 mb-1 block">群名称</label>
              {editingName ? (
                <div className="flex gap-2">
                  <input
                    value={nameInput}
                    onChange={e => setNameInput(e.target.value)}
                    className="flex-1 border border-gray-300 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-green-400"
                  />
                  <button onClick={saveInfo} className="text-xs bg-green-500 text-white px-2 py-1 rounded-lg">保存</button>
                  <button onClick={() => setEditingName(false)} className="text-xs text-gray-400 px-2 py-1">取消</button>
                </div>
              ) : (
                <div
                  className="text-sm text-gray-800 py-1 px-2 rounded-lg hover:bg-gray-50 cursor-pointer flex items-center justify-between"
                  onClick={() => setEditingName(true)}
                >
                  {localGroup.name}
                  <ChevronRight size={14} className="text-gray-400" />
                </div>
              )}
            </div>
            <div>
              <label className="text-xs text-gray-500 mb-1 block">群描述</label>
              <textarea
                value={descInput}
                onChange={e => setDescInput(e.target.value)}
                onBlur={saveInfo}
                rows={2}
                placeholder="添加群描述..."
                className="w-full border border-gray-200 rounded-lg px-2 py-1 text-sm focus:outline-none focus:border-green-400 resize-none"
              />
            </div>
          </div>
        </section>

        {/* 成员列表 */}
        <section className="p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs text-gray-400 uppercase tracking-wide">成员（{localGroup.members.length}）</div>
            {availableAgents.length > 0 && (
              <button
                onClick={() => setShowAddMember(v => !v)}
                className="text-xs text-green-500 hover:text-green-600 flex items-center gap-1"
              >
                <Plus size={12} /> 添加成员
              </button>
            )}
          </div>

          {/* 添加成员选择器 */}
          {showAddMember && availableAgents.length > 0 && (
            <div className="mb-3 border border-gray-200 rounded-xl overflow-hidden">
              {availableAgents.map(agent => (
                <button
                  key={agent.code}
                  onClick={() => addMember(agent.code)}
                  className="w-full flex items-center gap-2 p-2.5 hover:bg-gray-50 text-left border-b border-gray-100 last:border-0"
                >
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
                  {/* 操作按钮 — demo 里默认当前用户是群主 */}
                  <div className="flex items-center gap-1">
                    {/* 禁言/解禁（管理员及以上可操作，不能操作 owner） */}
                    {member.role !== 'owner' && (
                      <button
                        onClick={() => toggleMute(member.agent_code, member.muted)}
                        className={`p-1 rounded-lg transition-colors ${member.muted ? 'text-red-400 hover:bg-red-50' : 'text-gray-400 hover:bg-gray-100'}`}
                        title={member.muted ? '解除禁言' : '禁言'}
                      >
                        <Ban size={14} />
                      </button>
                    )}
                    {/* 设置角色（群主可以提升/降级，不能操作自己） */}
                    {member.role !== 'owner' && (
                      <select
                        value={member.role}
                        onChange={e => setRole(member.agent_code, e.target.value)}
                        className="text-xs border border-gray-200 rounded-lg px-1.5 py-1 bg-white focus:outline-none text-gray-600"
                        title="修改角色"
                      >
                        <option value="admin">管理员</option>
                        <option value="member">成员</option>
                      </select>
                    )}
                    {/* 踢出（群主/管理员可以，不能踢 owner） */}
                    {member.role !== 'owner' && (
                      <button
                        onClick={() => kickMember(member.agent_code)}
                        className="p-1 rounded-lg text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                        title="踢出成员"
                      >
                        <UserMinus size={14} />
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        {/* 危险区 */}
        <section className="p-4 border-t border-gray-100">
          <button
            onClick={dissolveGroup}
            className="w-full text-center text-sm text-red-500 hover:text-red-600 py-2 rounded-xl hover:bg-red-50 transition-colors"
          >
            解散群聊
          </button>
        </section>
      </div>
    </div>
  )
}

// ── 主页面 ────────────────────────────────────────────────────
export default function GroupPage() {
  const [groups, setGroups] = useState<GroupInfo[]>([])
  const [selectedGroup, setSelectedGroup] = useState<GroupInfo | null>(null)
  const [agentMap, setAgentMap] = useState<Record<string, AgentInfo>>({})
  const [allAgents, setAllAgents] = useState<AgentInfo[]>([])
  const [messages, setMessages] = useState<GroupMessage[]>([])
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const [speakingAgents, setSpeakingAgents] = useState<string[]>([])
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const loadGroups = useCallback(async () => {
    const res = await fetch(`${BASE_URL}/api/groups`)
    const gs: GroupInfo[] = await res.json()
    setGroups(gs)
    return gs
  }, [])

  useEffect(() => {
    loadGroups().then(gs => {
      if (gs.length > 0 && !selectedGroup) setSelectedGroup(gs[0])
    })
    fetch(`${BASE_URL}/api/agents`)
      .then(r => r.json())
      .then((agents: AgentInfo[]) => {
        setAllAgents(agents)
        const map: Record<string, AgentInfo> = {}
        agents.forEach(a => { map[a.code] = a })
        setAgentMap(map)
      })
  }, [])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = async () => {
    if (!input.trim() || !selectedGroup || isSending) return
    const text = input.trim()
    setInput('')
    setIsSending(true)

    const userMsg: GroupMessage = {
      id: Date.now().toString(),
      type: 'user',
      content: text,
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])

    try {
      const res = await fetch(`${BASE_URL}/api/groups/${selectedGroup.group_id}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ group_id: selectedGroup.group_id, message: text, user_id: 'user_001' }),
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
              setMessages(prev => [...prev, {
                id: msgId, type: 'agent',
                agent_code: event.agent_code,
                agent_name: event.agent_name || agentMap[event.agent_code]?.name || event.agent_code,
                content: '', isStreaming: true, timestamp: new Date(),
              }])
            } else if (event.type === 'token') {
              const msgId = streamingIds[event.agent_code]
              if (msgId) setMessages(prev => prev.map(m => m.id === msgId ? { ...m, content: m.content + event.content } : m))
            } else if (event.type === 'agent_done') {
              const msgId = streamingIds[event.agent_code]
              const clean = event.content.replace(/<think>[\s\S]*?<\/think>/g, '').trim()
              if (msgId) setMessages(prev => prev.map(m => m.id === msgId ? { ...m, content: clean, isStreaming: false } : m))
              delete streamingIds[event.agent_code]
            } else if (event.type === 'group_done') {
              setSpeakingAgents([])
            } else if (event.type === 'system') {
              setMessages(prev => [...prev, { id: Date.now().toString(), type: 'system', content: event.content, timestamp: new Date() }])
            }
          } catch { /* ignore parse errors */ }
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
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage() }
  }

  const handleGroupCreated = async (group: GroupInfo) => {
    setShowCreateModal(false)
    const gs = await loadGroups()
    const fresh = gs.find(g => g.group_id === group.group_id)
    if (fresh) setSelectedGroup(fresh)
    setMessages([])
    setShowSettings(false)
  }

  const handleGroupUpdated = (updated: GroupInfo) => {
    setGroups(prev => prev.map(g => g.group_id === updated.group_id ? updated : g))
    setSelectedGroup(updated)
  }

  const handleGroupDeleted = async () => {
    setShowSettings(false)
    const gs = await loadGroups()
    setSelectedGroup(gs.length > 0 ? gs[0] : null)
    setMessages([])
  }

  const selectGroup = (group: GroupInfo) => {
    setSelectedGroup(group)
    setMessages([])
    setShowSettings(false)
  }

  return (
    <div className="flex h-full bg-gray-100 relative overflow-hidden">
      {/* 左侧群列表 */}
      <aside className="w-16 md:w-56 bg-white border-r border-gray-200 flex flex-col flex-shrink-0">
        <div className="p-3 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700 hidden md:block">群聊</h2>
          <button
            onClick={() => setShowCreateModal(true)}
            className="w-7 h-7 rounded-lg bg-green-500 text-white flex items-center justify-center hover:bg-green-600 transition-colors flex-shrink-0"
            title="创建群聊"
          >
            <Plus size={14} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {groups.map(group => (
            <button
              key={group.group_id}
              onClick={() => selectGroup(group)}
              className={`w-full flex items-center gap-3 px-3 py-3 hover:bg-gray-50 transition-colors ${selectedGroup?.group_id === group.group_id ? 'bg-gray-100' : ''}`}
            >
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-green-400 to-emerald-600 flex items-center justify-center text-white font-bold flex-shrink-0 text-sm">
                {group.name[0]}
              </div>
              <div className="flex-1 text-left min-w-0 hidden md:block">
                <div className="text-sm font-medium text-gray-800 truncate">{group.name}</div>
                <div className="text-xs text-gray-400">{group.member_count ?? group.members.length} 个成员</div>
              </div>
            </button>
          ))}
          {groups.length === 0 && (
            <div className="p-4 text-center text-xs text-gray-400">还没有群聊，点 + 创建一个</div>
          )}
        </div>
      </aside>

      {/* 右侧聊天区 */}
      <main className="flex-1 flex flex-col min-w-0 relative">
        {selectedGroup ? (
          <>
            <header className="flex items-center gap-3 px-4 py-3 bg-white border-b border-gray-200 z-10">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-green-400 to-emerald-600 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
                {selectedGroup.name[0]}
              </div>
              <div className="flex-1 min-w-0">
                <div className="font-semibold text-gray-800 truncate">{selectedGroup.name}</div>
                <div className="text-xs text-gray-400">{selectedGroup.members.length} 个 AI 成员</div>
              </div>
              <div className="flex items-center gap-2">
                <div className="flex -space-x-2">
                  {selectedGroup.members.slice(0, 3).map(m => (
                    <AvatarBubble key={m.agent_code} name={agentMap[m.agent_code]?.name || m.agent_code} code={m.agent_code} size="sm" className="border-2 border-white" />
                  ))}
                </div>
                <button
                  onClick={() => setShowSettings(v => !v)}
                  className={`p-2 rounded-xl transition-colors ${showSettings ? 'bg-gray-100 text-gray-700' : 'text-gray-400 hover:bg-gray-50 hover:text-gray-600'}`}
                  title="群设置"
                >
                  <Settings size={18} />
                </button>
              </div>
            </header>

            <div className="flex-1 overflow-y-auto px-4 py-4 space-y-3">
              {messages.length === 0 && (
                <div className="flex flex-col items-center justify-center h-full text-gray-400">
                  <Users size={48} className="mb-3 opacity-30" />
                  <p className="text-sm">向群里发一条消息，看看 AI 们怎么回应</p>
                  <p className="text-xs mt-1 text-gray-300">@名字 指定成员 · @all 呼叫所有人</p>
                </div>
              )}
              {messages.map(msg => {
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
              <div ref={messagesEndRef} />
            </div>

            <div className="px-4 py-3 bg-white border-t border-gray-200">
              <div className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={e => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={`发消息到 ${selectedGroup.name}...`}
                  rows={1}
                  disabled={isSending}
                  className="flex-1 resize-none rounded-2xl border border-gray-300 px-4 py-2.5 text-sm focus:outline-none focus:border-green-400 transition-colors disabled:opacity-50 max-h-32"
                  style={{ minHeight: '42px' }}
                  onInput={e => { const el = e.currentTarget; el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 128) + 'px' }}
                />
                <button
                  onClick={sendMessage}
                  disabled={!input.trim() || isSending}
                  className="w-10 h-10 rounded-full bg-green-500 text-white flex items-center justify-center flex-shrink-0 hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Send size={18} />
                </button>
              </div>
              <p className="text-xs text-gray-400 mt-1 px-1">Enter 发送 · Shift+Enter 换行 · @名字 指定成员 · @all 全员</p>
            </div>

            {/* 群设置抽屉（absolute 在 main 内） */}
            {showSettings && selectedGroup && (
              <GroupSettingsDrawer
                group={selectedGroup}
                agents={allAgents}
                onClose={() => setShowSettings(false)}
                onGroupUpdated={handleGroupUpdated}
                onGroupDeleted={handleGroupDeleted}
              />
            )}
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-gray-400 gap-3">
            <Users size={48} className="opacity-30" />
            <p className="text-sm">选择一个群聊，或点击 + 创建新群</p>
            <button
              onClick={() => setShowCreateModal(true)}
              className="text-sm text-green-500 hover:text-green-600 underline"
            >创建群聊</button>
          </div>
        )}
      </main>

      {/* 建群 Modal */}
      {showCreateModal && (
        <CreateGroupModal
          agents={allAgents}
          onClose={() => setShowCreateModal(false)}
          onCreated={handleGroupCreated}
        />
      )}
    </div>
  )
}
