// App.tsx - Tab 导航框架（微信风格）
import { useState } from 'react'
import { MessageCircle, Users, User } from 'lucide-react'
import ChatPage from './pages/Chat'
import ContactsPage from './pages/Contacts'
import ProfilePage from './pages/Profile'
import TabBar from './components/TabBar'

const tabs = [
  { id: 'chat', label: '会话', icon: MessageCircle, component: ChatPage },
  { id: 'contacts', label: '联系人', icon: Users, component: ContactsPage },
  { id: 'profile', label: '我的', icon: User, component: ProfilePage },
]

export default function App() {
  const [activeTab, setActiveTab] = useState('chat')
  const ActiveComponent = tabs.find((t) => t.id === activeTab)!.component

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
