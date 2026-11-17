import { NavLink, Navigate, Route, Routes } from 'react-router'
import CalendarPage from './calendar/CalendarPage'
import AssetPage from './inbox/AssetPage'
import InboxPage from './inbox/InboxPage'
import Agent from './pages/Agent'
import Analytics from './pages/Analytics'
import Placeholder from './pages/Placeholder'
import Posts, { PostPage } from './pages/Posts'
import Settings from './pages/Settings'
import Trends from './pages/Trends'
import TokenBanner from './TokenBanner'

const TABS = [
  { path: '/inbox', label: 'Inbox' },
  { path: '/calendar', label: 'Calendar' },
  { path: '/analytics', label: 'Analytics' },
  { path: '/learnings', label: 'Learnings' },
  { path: '/ads', label: 'Ads' },
  { path: '/agent', label: 'Agent' },
  { path: '/settings', label: 'Settings' },
]

// Phone: header + bottom tab bar. md and up: side nav.
export default function App() {
  return (
    <div className="min-h-dvh bg-gray-50 text-gray-900 md:flex">
      <nav
        aria-label="Main"
        className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-7 border-t border-gray-200 bg-white pb-[env(safe-area-inset-bottom)] md:static md:flex md:w-48 md:shrink-0 md:flex-col md:gap-1 md:border-t-0 md:border-r md:p-3"
      >
        {TABS.map((t) => (
          <NavLink
            key={t.path}
            to={t.path}
            className={({ isActive }) =>
              `flex min-h-11 items-center justify-center px-1 text-xs font-medium md:justify-start md:rounded-lg md:px-3 md:text-sm ${
                isActive ? 'text-blue-600 md:bg-blue-50' : 'text-gray-600 hover:text-gray-900'
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>
      <div className="flex-1 pb-16 md:pb-0">
        <header className="border-b border-gray-200 bg-white px-4 py-3">
          <h1 className="text-lg font-bold">Growth Studio</h1>
        </header>
        <TokenBanner />
        <main className="p-4">
          <Routes>
            <Route path="/" element={<Navigate to="/inbox" replace />} />
            {TABS.map((t) => (
              <Route
                key={t.path}
                path={t.path}
                element={
                  t.path === '/inbox' ? <InboxPage /> :
                  t.path === '/calendar' ? <CalendarPage /> :
                  t.path === '/agent' ? <Agent /> :
                  t.path === '/analytics' ? <Analytics /> :
                  t.path === '/settings' ? <Settings /> : <Placeholder title={t.label} />
                }
              />
            ))}
            <Route path="/assets/:id" element={<AssetPage />} />
            <Route path="/trends" element={<Trends />} />
            <Route path="/analytics/posts" element={<Posts />} />
            <Route path="/analytics/posts/:id" element={<PostPage />} />
            <Route path="*" element={<Placeholder title="Not found" />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}
