// components/MessageBubble.tsx - 消息气泡组件
interface MessageBubbleProps {
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  agentName?: string
  agentAvatar?: string
}

// 简单 markdown 渲染：支持粗体、换行
function renderContent(content: string) {
  const parts = content.split(/(\*\*.*?\*\*)/g)
  return parts.map((part, i) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    // 处理换行
    return part.split('\n').map((line, j) => (
      <span key={`${i}-${j}`}>
        {line}
        {j < part.split('\n').length - 1 && <br />}
      </span>
    ))
  })
}

export default function MessageBubble({
  role,
  content,
  isStreaming,
  agentName,
  agentAvatar,
}: MessageBubbleProps) {
  const isUser = role === 'user'

  return (
    <div className={`flex items-end gap-2 mb-3 ${isUser ? 'flex-row-reverse' : 'flex-row'}`}>
      {/* 头像 */}
      {!isUser && (
        <div className="w-9 h-9 rounded-full bg-gray-200 flex items-center justify-center text-lg flex-shrink-0">
          {agentAvatar || '🤖'}
        </div>
      )}
      {isUser && (
        <div className="w-9 h-9 rounded-full bg-green-500 flex items-center justify-center text-white text-sm font-bold flex-shrink-0">
          我
        </div>
      )}

      <div className={`flex flex-col ${isUser ? 'items-end' : 'items-start'} max-w-[70%]`}>
        {/* 发送者名称 */}
        {!isUser && agentName && (
          <span className="text-xs text-gray-500 mb-1 px-1">{agentName}</span>
        )}

        {/* 气泡 */}
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm leading-relaxed break-words ${
            isUser
              ? 'bg-green-500 text-white rounded-br-sm'
              : 'bg-white text-gray-800 shadow-sm rounded-bl-sm'
          }`}
        >
          {renderContent(content)}
          {isStreaming && (
            <span className="inline-block w-1 h-4 bg-current ml-0.5 animate-pulse rounded-full" />
          )}
        </div>
      </div>
    </div>
  )
}
