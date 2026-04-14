// pages/Contacts/index.tsx - 联系人页（完善版）
import { useState, useEffect, useCallback } from 'react'
import { Plus, X, Sparkles, Search, Trash2, MessageCircle, ChevronDown, ChevronUp } from 'lucide-react'
import { api } from '../../api/client'
import type { AgentSummary } from '../../api/client'
import AvatarBubble from '../../components/AvatarBubble'

interface AgentDetail extends AgentSummary {
  soul?: string
}

const BUILT_IN_CODES = ['haji_assistant', 'haji_coder']

export default function ContactsPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const [createResult, setCreateResult] = useState<string | null>(null)
  const [backendError, setBackendError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [selectedAgent, setSelectedAgent] = useState<AgentDetail | null>(null)
  const [showDrawer, setShowDrawer] = useState(false)
  const [soulExpanded, setSoulExpanded] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const loadAgents = useCallback(() => {
    setLoading(true)
    api.getAgents()
      .then((data) => {
        setAgents(data)
        setLoading(false)
        setBackendError(null)
      })
      .catch((err) => {
        setBackendError('无法连接后端')
        setLoading(false)
        console.error(err)
      })
  }, [])

  useEffect(() => {
    loadAgents()
  }, [loadAgents])

  const filteredAgents = agents.filter((a) => {
    const q = search.toLowerCase()
    return (
      a.name.toLowerCase().includes(q) ||
      (a.bio || '').toLowerCase().includes(q) ||
      a.tags.some((t) => t.toLowerCase().includes(q))
    )
  })

  const handleSelectAgent = async (agent: AgentSummary) => {
    setSoulExpanded(false)
    setSelectedAgent(agent as AgentDetail)
    setShowDrawer(true)
    // 尝试获取 soul 详情
    try {
      const detail = await api.getAgent(agent.code)
      setSelectedAgent((prev) => prev?.code === agent.code ? { ...prev, soul: detail.soul } : prev)
    } catch {
      // ignore
    }
  }

  const handleSendMessage = () => {
    if (!selectedAgent) return
    localStorage.setItem('haji_action', JSON.stringify({ action: 'openChat', agentCode: selectedAgent.code }))
    // Dispatch storage event for same-tab detection
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'haji_action',
      newValue: JSON.stringify({ action: 'openChat', agentCode: selectedAgent.code }),
    }))
    setShowDrawer(false)
  }

  const handleDelete = async () => {
    if (!selectedAgent) return
    if (BUILT_IN_CODES.includes(selectedAgent.code)) return
    setDeleting(true)
    try {
      await api.deleteAgent(selectedAgent.code)
      setAgents((prev) => prev.filter((a) => a.code !== selectedAgent.code))
      setShowDrawer(false)
      setSelectedAgent(null)
    } catch (err) {
      console.error('删除失败', err)
    } finally {
      setDeleting(false)
    }
  }

  const handleCreate = async () => {
    if (!description.trim() || creating) return
    setCreating(true)
    setCreateResult(null)

    try {
      const result = await api.createAgent(description.trim())
      if (result.ok) {
        setCreateResult(`✅ 创建成功！Agent: ${result.agent_code}`)
        setDescription('')
        setTimeout(() => {
          loadAgents()
          setShowCreate(false)
          setCreateResult(null)
        }, 2000)
      } else {
        const errors = (result.errors || []).map((e) => `[${e.field}] ${e.message}`).join('\n')
        setCreateResult(`❌ 创建失败：\n${errors}`)
      }
    } catch (err) {
      setCreateResult(`❌ 请求失败：${String(err)}`)
    } finally {
      setCreating(false)
    }
  }

  const isBuiltIn = selectedAgent ? BUILT_IN_CODES.includes(selectedAgent.code) : false

  return (
    <div className="flex flex-col h-full bg-gray-50 relative">
      {/* 顶部搜索栏 */}
      <header className="bg-white border-b border-gray-200 px-4 pt-3 pb-2">
        <h1 className="font-semibold text-gray-800 mb-2">AI 联系人</h1>
        <div className="flex items-center gap-2 bg-gray-100 rounded-xl px-3 py-2">
          <Search size={16} className="text-gray-400 flex-shrink-0" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索联系人..."
            className="flex-1 bg-transparent text-sm outline-none text-gray-700 placeholder-gray-400"
          />
          {search && (
            <button onClick={() => setSearch('')} className="text-gray-400 hover:text-gray-600">
              <X size={14} />
            </button>
          )}
        </div>
      </header>

      {/* 联系人列表 */}
      <div className="flex-1 overflow-y-auto pb-20">
        {loading && (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm">加载中...</div>
        )}
        {backendError && (
          <div className="m-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {backendError}
          </div>
        )}
        {!loading && filteredAgents.length === 0 && !backendError && (
          <div className="flex flex-col items-center justify-center h-48 text-gray-400">
            <div className="text-4xl mb-2">👥</div>
            <p className="text-sm">{search ? '没有匹配的联系人' : '还没有 AI 联系人'}</p>
            {!search && <p className="text-xs mt-1">点击下方按钮创建第一个</p>}
          </div>
        )}

        {filteredAgents.map((agent) => (
          <div
            key={agent.code}
            onClick={() => handleSelectAgent(agent)}
            className="flex items-center gap-4 px-4 py-3 bg-white border-b border-gray-100 hover:bg-gray-50 active:bg-gray-100 transition-colors cursor-pointer"
          >
            {/* 头像 */}
            <AvatarBubble name={agent.name} code={agent.code} size="md" />

            {/* 信息 */}
            <div className="flex-1 min-w-0">
              <div className="font-medium text-gray-800">{agent.name}</div>
              <div className="text-sm text-gray-500 truncate">{agent.bio || '暂无签名'}</div>
              {agent.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="text-xs bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded-full"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {/* 模式标签 */}
            <div className="text-xs text-gray-400 bg-gray-100 px-2 py-1 rounded-full flex-shrink-0">
              {agent.mode}
            </div>
          </div>
        ))}
      </div>

      {/* 创建新联系人按钮 */}
      <div className="absolute bottom-0 left-0 right-0 px-4 py-3 bg-white border-t border-gray-200">
        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-green-500 text-white font-medium hover:bg-green-600 active:scale-95 transition-all"
          >
            <Plus size={20} />
            创建 AI 联系人
          </button>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                <Sparkles size={16} className="text-yellow-500" />
                描述你想要的 AI 朋友
              </div>
              <button
                onClick={() => { setShowCreate(false); setDescription(''); setCreateResult(null) }}
                className="p-1 rounded-full hover:bg-gray-100 text-gray-500"
              >
                <X size={18} />
              </button>
            </div>

            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="描述你想要的 AI 朋友，比如：一个懂投资的朋友，说话直接，不废话"
              rows={3}
              className="w-full rounded-xl border border-gray-300 px-3 py-2.5 text-sm focus:outline-none focus:border-green-400 resize-none transition-colors"
            />

            {createResult && (
              <div className={`text-sm p-2.5 rounded-lg whitespace-pre-wrap ${
                createResult.startsWith('✅') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600'
              }`}>
                {createResult}
              </div>
            )}

            <button
              onClick={handleCreate}
              disabled={!description.trim() || creating}
              className="w-full py-2.5 rounded-xl bg-green-500 text-white font-medium hover:bg-green-600 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
            >
              {creating ? (
                <>
                  <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  AI 正在设计...
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  AI 帮我创建
                </>
              )}
            </button>
          </div>
        )}
      </div>

      {/* 详情抽屉（移动端底部弹出 / 桌面端右侧面板） */}
      {showDrawer && selectedAgent && (
        <>
          {/* 遮罩 */}
          <div
            className="absolute inset-0 bg-black/30 z-10"
            onClick={() => setShowDrawer(false)}
          />

          {/* 抽屉内容 */}
          <div className="absolute bottom-0 left-0 right-0 z-20 bg-white rounded-t-3xl shadow-2xl max-h-[80vh] overflow-y-auto">
            {/* 拖拽指示条 */}
            <div className="flex justify-center pt-3 pb-1">
              <div className="w-10 h-1 bg-gray-300 rounded-full" />
            </div>

            {/* 关闭按钮 */}
            <div className="flex justify-end px-4 pb-2">
              <button
                onClick={() => setShowDrawer(false)}
                className="p-1.5 rounded-full hover:bg-gray-100 text-gray-500"
              >
                <X size={20} />
              </button>
            </div>

            {/* 详情内容 */}
            <div className="px-6 pb-8 space-y-4">
              {/* Avatar + 基本信息 */}
              <div className="flex flex-col items-center text-center gap-2">
                <AvatarBubble name={selectedAgent.name} code={selectedAgent.code} size="xl" />
                <h2 className="text-xl font-bold text-gray-800">{selectedAgent.name}</h2>
                {selectedAgent.bio && (
                  <p className="text-sm text-gray-500">{selectedAgent.bio}</p>
                )}
              </div>

              {/* Tags */}
              {selectedAgent.tags.length > 0 && (
                <div className="flex flex-wrap justify-center gap-2">
                  {selectedAgent.tags.map((tag) => (
                    <span
                      key={tag}
                      className="text-xs bg-blue-50 text-blue-600 px-2.5 py-1 rounded-full font-medium"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              )}

              {/* Mode 徽章 */}
              <div className="flex justify-center">
                <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-3 py-1 rounded-full font-semibold">
                  {selectedAgent.mode === 'REACT' ? '⚡ ReAct 模式' : '🎯 Direct 模式'}
                </span>
              </div>

              {/* Soul 人设预览 */}
              {selectedAgent.soul && (
                <div className="bg-gray-50 rounded-2xl p-4">
                  <div className="text-xs font-semibold text-gray-500 mb-2 uppercase tracking-wide">人设</div>
                  <p className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap">
                    {soulExpanded
                      ? selectedAgent.soul
                      : selectedAgent.soul.slice(0, 150) + (selectedAgent.soul.length > 150 ? '...' : '')}
                  </p>
                  {selectedAgent.soul.length > 150 && (
                    <button
                      onClick={() => setSoulExpanded(!soulExpanded)}
                      className="mt-2 flex items-center gap-1 text-xs text-blue-500 hover:text-blue-600"
                    >
                      {soulExpanded ? <><ChevronUp size={14} />收起</> : <><ChevronDown size={14} />展开全部</>}
                    </button>
                  )}
                </div>
              )}

              {/* 操作按钮 */}
              <div className="flex gap-3 pt-2">
                <button
                  onClick={handleSendMessage}
                  className="flex-1 flex items-center justify-center gap-2 py-3 rounded-xl bg-green-500 text-white font-medium hover:bg-green-600 transition-colors"
                >
                  <MessageCircle size={18} />
                  发消息
                </button>
                <button
                  onClick={handleDelete}
                  disabled={isBuiltIn || deleting}
                  title={isBuiltIn ? '内置联系人不可删除' : '删除联系人'}
                  className="flex items-center justify-center gap-2 px-4 py-3 rounded-xl border border-gray-200 text-gray-500 hover:bg-red-50 hover:text-red-500 hover:border-red-200 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  {deleting ? (
                    <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                  ) : (
                    <Trash2 size={18} />
                  )}
                </button>
              </div>

              {isBuiltIn && (
                <p className="text-xs text-center text-gray-400">内置联系人不可删除</p>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
