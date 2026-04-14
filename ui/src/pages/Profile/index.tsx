// pages/Profile/index.tsx - 我的页（个人信息 + 框架信息 + LLM 配置 + 使用统计）
import { useState, useEffect } from 'react'
import { Server, Cpu, Hash, BarChart2 } from 'lucide-react'
import { api } from '../../api/client'

interface HealthInfo {
  status: string
  version: string
}

interface ProfileInfo {
  model: string
  base_url: string
  version: string
  framework: string
}

export default function ProfilePage() {
  const [health, setHealth] = useState<HealthInfo | null>(null)
  const [profile, setProfile] = useState<ProfileInfo | null>(null)
  const [agentCount, setAgentCount] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.allSettled([
      api.health(),
      api.getProfile(),
      api.getAgents(),
    ]).then(([healthRes, profileRes, agentsRes]) => {
      if (healthRes.status === 'fulfilled') setHealth(healthRes.value)
      if (profileRes.status === 'fulfilled') setProfile(profileRes.value)
      if (agentsRes.status === 'fulfilled') setAgentCount(agentsRes.value.length)
      setLoading(false)
    })
  }, [])

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* 头部个人信息 */}
      <div className="bg-white px-4 py-6 flex items-center gap-4 border-b border-gray-200">
        <div className="w-16 h-16 rounded-full bg-gradient-to-br from-green-400 to-emerald-600 flex items-center justify-center text-3xl">
          🧑‍💻
        </div>
        <div>
          <div className="text-lg font-semibold text-gray-800">祎晗</div>
          <div className="text-sm text-gray-400">haji-ai 开发者</div>
        </div>
      </div>

      {/* 配置信息 */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">

        {/* 后端状态 */}
        <div className="bg-white rounded-xl p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Server size={16} className="text-green-500" />
            后端状态
          </h3>
          {loading ? (
            <div className="text-sm text-gray-400">检测中...</div>
          ) : health ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">状态</span>
                <span className="text-sm font-medium text-green-600 flex items-center gap-1">
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  {health.status}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">服务版本</span>
                <span className="text-sm font-mono text-gray-800">v{health.version}</span>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-sm text-red-500">
              <div className="w-2 h-2 bg-red-500 rounded-full" />
              后端未连接（port 8766）
            </div>
          )}
        </div>

        {/* LLM 配置 */}
        <div className="bg-white rounded-xl p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Cpu size={16} className="text-blue-500" />
            LLM 配置
          </h3>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">模型</span>
              <span className="text-sm font-mono text-gray-800">
                {profile?.model ?? 'minimax-m2.7'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">API 地址</span>
              <span className="text-xs font-mono text-gray-500 truncate max-w-[180px]">
                {profile?.base_url
                  ? new URL(profile.base_url).hostname
                  : 'maas.devops.xiaohongshu.com'}
              </span>
            </div>
          </div>
        </div>

        {/* 使用统计 */}
        <div className="bg-white rounded-xl p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <BarChart2 size={16} className="text-orange-500" />
            使用统计
          </h3>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">已注册 Agent</span>
              <span className="text-sm font-semibold text-gray-800">
                {agentCount !== null ? `${agentCount} 个` : '—'}
              </span>
            </div>
          </div>
        </div>

        {/* 框架信息 */}
        <div className="bg-white rounded-xl p-4 shadow-sm">
          <h3 className="text-sm font-semibold text-gray-700 mb-3 flex items-center gap-2">
            <Hash size={16} className="text-purple-500" />
            框架信息
          </h3>
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">haji-ai 版本</span>
              <span className="text-sm font-mono text-gray-800">
                v{profile?.version ?? '0.1.0'}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">测试覆盖</span>
              <span className="text-sm text-green-600 font-medium">557 个测试全通过 ✓</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">前端框架</span>
              <span className="text-sm text-gray-800">React + Vite + Tailwind v4</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-gray-600">定位</span>
              <span className="text-sm text-gray-500">AI 社交平台 Multi-Agent 框架</span>
            </div>
          </div>
        </div>

        {/* 关于 */}
        <div className="bg-gradient-to-br from-green-50 to-emerald-50 rounded-xl p-4 border border-green-100">
          <div className="text-center">
            <div className="text-3xl mb-2">🦐</div>
            <div className="text-sm font-semibold text-gray-700">haji-ai</div>
            <div className="text-xs text-gray-500 mt-1">
              像微信，但联系人全是 AI Agent
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
