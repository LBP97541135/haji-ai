// pages/Contacts/index.tsx - 联系人页
import { useState, useEffect, useCallback } from 'react'
import { Plus, X, Sparkles, RefreshCw } from 'lucide-react'
import { api } from '../../api/client'
import type { AgentSummary } from '../../api/client'

export default function ContactsPage() {
  const [agents, setAgents] = useState<AgentSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [description, setDescription] = useState('')
  const [creating, setCreating] = useState(false)
  const [createResult, setCreateResult] = useState<string | null>(null)
  const [backendError, setBackendError] = useState<string | null>(null)

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

  const handleCreate = async () => {
    if (!description.trim() || creating) return
    setCreating(true)
    setCreateResult(null)

    try {
      const result = await api.createAgent(description.trim())
      if (result.ok) {
        setCreateResult(`✅ 创建成功！Agent: ${result.agent_code}`)
        setDescription('')
        // 刷新列表
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

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* 标题栏 */}
      <header className="flex items-center justify-between px-4 py-3 bg-white border-b border-gray-200">
        <h1 className="font-semibold text-gray-800">AI 联系人</h1>
        <button
          onClick={() => loadAgents()}
          className="p-1.5 rounded-full hover:bg-gray-100 text-gray-500 transition-colors"
          title="刷新"
        >
          <RefreshCw size={18} />
        </button>
      </header>

      {/* 联系人列表 */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm">
            加载中...
          </div>
        )}
        {backendError && (
          <div className="m-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {backendError}
          </div>
        )}
        {!loading && agents.length === 0 && !backendError && (
          <div className="flex flex-col items-center justify-center h-48 text-gray-400">
            <div className="text-4xl mb-2">🤖</div>
            <p className="text-sm">还没有 AI 联系人</p>
            <p className="text-xs mt-1">点击下方按钮创建第一个</p>
          </div>
        )}

        {agents.map((agent) => (
          <div
            key={agent.code}
            className="flex items-center gap-4 px-4 py-3 bg-white border-b border-gray-100 hover:bg-gray-50 transition-colors"
          >
            {/* 头像 */}
            <div className="w-12 h-12 rounded-full bg-gradient-to-br from-blue-100 to-purple-100 flex items-center justify-center text-2xl flex-shrink-0">
              {agent.avatar || '🤖'}
            </div>

            {/* 信息 */}
            <div className="flex-1 min-w-0">
              <div className="font-medium text-gray-800">{agent.name}</div>
              <div className="text-sm text-gray-500 truncate">{agent.bio || '暂无签名'}</div>
              {agent.tags.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.tags.slice(0, 3).map((tag) => (
                    <span
                      key={tag}
                      className="text-xs bg-green-50 text-green-600 px-1.5 py-0.5 rounded-full"
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
      <div className="px-4 py-3 bg-white border-t border-gray-200">
        {!showCreate ? (
          <button
            onClick={() => setShowCreate(true)}
            className="w-full flex items-center justify-center gap-2 py-3 rounded-xl bg-green-500 text-white font-medium hover:bg-green-600 active:scale-98 transition-all"
          >
            <Plus size={20} />
            创建新 AI 联系人
          </button>
        ) : (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-sm font-medium text-gray-700">
                <Sparkles size={16} className="text-yellow-500" />
                用自然语言描述你想要的 AI 朋友
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
              placeholder="例如：我想要一个懂投资的朋友，说话直接，能给我分析股票市场..."
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
    </div>
  )
}
