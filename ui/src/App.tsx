// App.tsx - Tab 导航框架（微信风格）
import { useState, useEffect } from 'react'
import { MessageCircle, Users, User, Heart, MessagesSquare } from 'lucide-react'
import ChatPage from './pages/Chat'
import ContactsPage from './pages/Contacts'
import MomentsPage from './pages/Moments'
import ProfilePage from './pages/Profile'
import GroupPage from './pages/Group'
import TabBar from './components/TabBar'

const tabs = [
  { id: 'chat', label: '会话', icon: MessageCircle, component: ChatPage },
  { id: 'group', label: '群聊', icon: MessagesSquare, component: GroupPage },
  { id: 'contacts', label: '联系人', icon: Users, component: ContactsPage },
  { id: 'moments', label: '朋友圈', icon: Heart, component: MomentsPage },
  { id: 'profile', label: '我的', icon: User, component: ProfilePage },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('chat')
  const ActiveComponent = tabs.find((t) => t.id === activeTab)!.component

  // 监听联系人页发来的 openChat 指令（localStorage）
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key !== 'haji_action') return
      try {
        const payload = JSON.parse(e.newValue || '{}')
        if (payload.action === 'openChat') {
          setActiveTab('chat')
          localStorage.removeItem('haji_action')
        }
      } catch {
        // ignore
      }
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  return (
    <div className="flex flex-col h-screen bg-gray-100 max-w-2xl mx-auto shadow-xl">
      <main className="flex-1 overflow-hidden">
        <ActiveComponent />
      </main>
      <TabBar
        tabs={tabs.map(({ id, label, icon }) => ({ id, label, icon }))}
        activeTab={activeTab}
        onTabChange={setActiveTab}
      />
    </div>
  )
}
