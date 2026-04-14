// components/AvatarBubble.tsx - 彩色字母头像（emoji 在容器环境不可靠）
const COLORS = [
  'bg-emerald-500', 'bg-blue-500', 'bg-purple-500', 'bg-orange-500',
  'bg-pink-500', 'bg-indigo-500', 'bg-teal-500', 'bg-rose-500',
]

function colorForCode(code: string): string {
  let h = 0
  for (let i = 0; i < code.length; i++) h = (h * 31 + code.charCodeAt(i)) & 0xffff
  return COLORS[h % COLORS.length]
}

interface AvatarBubbleProps {
  name: string
  code: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  className?: string
}

const SIZE_MAP = {
  sm: 'w-8 h-8 text-sm',
  md: 'w-10 h-10 text-base',
  lg: 'w-14 h-14 text-2xl',
  xl: 'w-20 h-20 text-4xl',
}

export default function AvatarBubble({ name, code, size = 'md', className = '' }: AvatarBubbleProps) {
  const letter = name ? name[0].toUpperCase() : '?'
  const color = colorForCode(code)
  return (
    <div
      className={`${SIZE_MAP[size]} ${color} rounded-full flex items-center justify-center text-white font-bold flex-shrink-0 select-none ${className}`}
    >
      {letter}
    </div>
  )
}
