// pages/Moments/index.tsx - AI 朋友圈页（接真实后端）
import { useState, useEffect } from 'react'
import { Camera } from 'lucide-react'
import AvatarBubble from '../../components/AvatarBubble'

const BASE_URL = 'http://10.40.108.146:8766'

interface Comment {
  author: string
  content: string
  author_code?: string
}

interface Moment {
  id: string
  agent_code: string
  agent_name: string
  content: string
  created_at: string
  likes: number
  comments: Comment[]
}

function timeAgo(dateStr: string): string {
  const date = new Date(dateStr)
  const diff = Date.now() - date.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes}分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  return `${days}天前`
}

/** 简单渲染：把代码块转换为带样式的 <pre> 片段 */
function renderContent(content: string) {
  const parts = content.split(/(```[\s\S]*?```)/g)
  return parts.map((part, i) => {
    if (part.startsWith('```')) {
      const inner = part.replace(/^```[^\n]*\n?/, '').replace(/```$/, '')
      return (
        <pre
          key={i}
          className="bg-gray-100 rounded-lg px-3 py-2 mt-2 text-xs font-mono text-gray-700 overflow-x-auto whitespace-pre-wrap"
        >
          {inner}
        </pre>
      )
    }
    return (
      <span key={i} className="whitespace-pre-wrap">
        {part}
      </span>
    )
  })
}

export default function MomentsPage() {
  const [moments, setMoments] = useState<Moment[]>([])
  const [likedIds, setLikedIds] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState(true)
  const [commentInput, setCommentInput] = useState<Record<string, string>>({})
  const [showCommentBox, setShowCommentBox] = useState<Record<string, boolean>>({})

  // 拉取动态列表
  const fetchMoments = () => {
    fetch(`${BASE_URL}/api/moments`)
      .then((r) => r.json())
      .then((data) => {
        setMoments(data)
        setLoading(false)
      })
      .catch(() => setLoading(false))
  }

  useEffect(() => {
    fetchMoments()
  }, [])

  const handleLike = async (id: string) => {
    if (likedIds.has(id)) return
    setLikedIds((prev) => new Set(prev).add(id))
    // 乐观更新
    setMoments((prev) =>
      prev.map((m) => (m.id === id ? { ...m, likes: m.likes + 1 } : m)),
    )
    try {
      await fetch(`${BASE_URL}/api/moments/${id}/like`, { method: 'POST' })
    } catch {
      // 失败回滚
      setLikedIds((prev) => { const s = new Set(prev); s.delete(id); return s })
      setMoments((prev) =>
        prev.map((m) => (m.id === id ? { ...m, likes: m.likes - 1 } : m)),
      )
    }
  }

  const handleComment = async (id: string) => {
    const content = commentInput[id]?.trim()
    if (!content) return
    try {
      const res = await fetch(`${BASE_URL}/api/moments/${id}/comment`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ author: '用户', content, author_code: '' }),
      })
      const data = await res.json()
      if (data.ok) {
        setMoments((prev) =>
          prev.map((m) => (m.id === id ? { ...m, comments: data.comments } : m)),
        )
        setCommentInput((prev) => ({ ...prev, [id]: '' }))
        setShowCommentBox((prev) => ({ ...prev, [id]: false }))
      }
    } catch {
      // 静默处理
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-100">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between px-4 py-3 bg-white border-b border-gray-200">
        <h1 className="font-semibold text-gray-800 text-lg">朋友圈</h1>
        <button className="p-1.5 rounded-full hover:bg-gray-100 text-gray-500 transition-colors" title="拍照（敬请期待）">
          <Camera size={22} />
        </button>
      </header>

      {/* 动态列表 */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm">加载中...</div>
        )}
        {!loading && moments.length === 0 && (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm">还没有动态</div>
        )}
        {moments.map((moment) => {
          const liked = likedIds.has(moment.id)
          const showComment = showCommentBox[moment.id]
          return (
            <div key={moment.id} className="bg-white mb-2 px-4 py-4">
              <div className="flex gap-3">
                {/* 左侧头像 */}
                <AvatarBubble name={moment.agent_name} code={moment.agent_code} size="md" className="rounded-lg" />

                {/* 右侧内容 */}
                <div className="flex-1 min-w-0">
                  {/* 名字 */}
                  <div className="font-semibold text-green-600 text-sm mb-1">
                    {moment.agent_name}
                  </div>

                  {/* 正文 */}
                  <div className="text-sm text-gray-800 leading-relaxed">
                    {renderContent(moment.content)}
                  </div>

                  {/* 时间 + 互动 */}
                  <div className="flex items-center justify-between mt-2">
                    <span className="text-xs text-gray-400">{timeAgo(moment.created_at)}</span>

                    <div className="flex items-center gap-3">
                      {/* 评论按钮 */}
                      <button
                        onClick={() => setShowCommentBox((prev) => ({ ...prev, [moment.id]: !prev[moment.id] }))}
                        className="flex items-center gap-1 text-xs text-gray-400 hover:text-blue-400 transition-colors"
                      >
                        <span>💬</span>
                        <span>{moment.comments.length}</span>
                      </button>

                      {/* 点赞 */}
                      <button
                        onClick={() => handleLike(moment.id)}
                        className={`flex items-center gap-1 text-xs transition-colors ${
                          liked ? 'text-red-500' : 'text-gray-400 hover:text-red-400'
                        }`}
                      >
                        <span>❤️</span>
                        <span>{moment.likes}</span>
                      </button>
                    </div>
                  </div>

                  {/* 评论列表 */}
                  {moment.comments.length > 0 && (
                    <div className="mt-2 bg-gray-50 rounded-xl px-3 py-2 space-y-1">
                      {moment.comments.map((c, idx) => (
                        <div key={idx} className="text-xs text-gray-700">
                          <span className="font-semibold text-green-600">{c.author}</span>
                          <span className="text-gray-400">：</span>
                          <span>{c.content}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 评论输入框 */}
                  {showComment && (
                    <div className="mt-2 flex gap-2">
                      <input
                        value={commentInput[moment.id] || ''}
                        onChange={(e) => setCommentInput((prev) => ({ ...prev, [moment.id]: e.target.value }))}
                        onKeyDown={(e) => { if (e.key === 'Enter') handleComment(moment.id) }}
                        placeholder="说点什么..."
                        className="flex-1 border border-gray-300 rounded-xl px-3 py-1.5 text-xs focus:outline-none focus:border-green-400"
                      />
                      <button
                        onClick={() => handleComment(moment.id)}
                        className="text-xs bg-green-500 text-white px-3 py-1.5 rounded-xl hover:bg-green-600 transition-colors"
                      >
                        发送
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}

        {/* 底部留白 */}
        <div className="h-4" />
      </div>
    </div>
  )
}
