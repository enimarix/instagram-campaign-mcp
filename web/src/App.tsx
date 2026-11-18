import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router'
import CalendarPage from './calendar/CalendarPage'
import AssetPage from './inbox/AssetPage'
import InboxPage from './inbox/InboxPage'
import Agent from './pages/Agent'
import Analytics from './pages/Analytics'
import Breakdowns from './pages/Breakdowns'
import Placeholder from './pages/Placeholder'
import Posts, { PostPage } from './pages/Posts'
import ReportPage from './pages/Report'
import Settings from './pages/Settings'
import Trends from './pages/Trends'
import TokenBanner from './TokenBanner'
import {
  AgentIcon, BulbIcon, CalendarIcon, ChartIcon, ChevronIcon, InboxIcon, MegaphoneIcon, MoreIcon, SettingsIcon,
  TrendsIcon,
} from './ui/icons'
import { PageHeader } from './ui/PageHeader'
import { card } from './ui/styles'
import { ToastProvider } from './ui/Toast'

// `tab`: also in the phone's bottom bar; the rest sit behind "More" there.
const NAV = [
  { path: '/inbox', label: 'Inbox', Icon: InboxIcon, tab: true },
  { path: '/calendar', label: 'Calendar', Icon: CalendarIcon, tab: true },
  { path: '/analytics', label: 'Analytics', Icon: ChartIcon, tab: true },
  { path: '/trends', label: 'Trends', Icon: TrendsIcon },
  { path: '/learnings', label: 'Learnings', Icon: BulbIcon },
  { path: '/ads', label: 'Ads', Icon: MegaphoneIcon },
  { path: '/agent', label: 'Agent', Icon: AgentIcon, tab: true },
  { path: '/settings', label: 'Settings', Icon: SettingsIcon },
]
const MORE = NAV.filter((n) => !n.tab)

const sideLink = ({ isActive }: { isActive: boolean }) =>
  `flex min-h-11 items-center gap-3 rounded-control px-3 text-sm font-medium transition ${
    isActive ? 'bg-accent/12 text-accent' : 'text-muted hover:bg-surface-2 hover:text-fg'}`
const tabLink = (active: boolean) =>
  `flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] transition ${
    active ? 'font-semibold text-accent' : 'font-medium text-muted hover:text-fg'}`
// The icon sits in a pill that fills while its tab is current.
const tabIcon = (Icon: typeof InboxIcon, active: boolean) => (
  <span className={`rounded-full px-4 py-0.5 transition ${active ? 'bg-accent/15' : ''}`}><Icon /></span>
)

// Phone: pages + a bottom tab bar with icons. From lg (1024 px): a left sidebar.
export default function App() {
  const { pathname } = useLocation()
  const inMore = pathname === '/more' || MORE.some((n) => pathname.startsWith(n.path))
  return (
    <ToastProvider>
      <div className="min-h-dvh lg:flex">
        <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-line bg-surface px-3 py-6 lg:flex">
          <p className="flex items-center gap-2 px-3 text-base font-bold tracking-tight">
            <span aria-hidden className="grid size-7 place-items-center rounded-lg bg-accent text-xs font-black text-on-accent">GS</span>
            Growth Studio
          </p>
          <nav aria-label="Main" className="mt-6 flex flex-col gap-1">
            {NAV.map(({ path, label, Icon }) => (
              <NavLink key={path} to={path} className={sideLink}><Icon />{label}</NavLink>
            ))}
          </nav>
        </aside>

        <div className="min-w-0 flex-1 pb-[calc(3.5rem+env(safe-area-inset-bottom))] lg:pb-0">
          <TokenBanner />
          <main key={pathname}
            className="mx-auto w-full max-w-6xl animate-page-in pt-[max(1rem,env(safe-area-inset-top))] pr-[max(1rem,env(safe-area-inset-right))] pb-8 pl-[max(1rem,env(safe-area-inset-left))] lg:px-8 lg:pt-8">
            <Routes>
              <Route path="/" element={<Navigate to="/inbox" replace />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/calendar" element={<CalendarPage />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/analytics/posts" element={<Posts />} />
              <Route path="/analytics/posts/:id" element={<PostPage />} />
              <Route path="/analytics/breakdowns" element={<Breakdowns />} />
              <Route path="/reports" element={<ReportPage />} />
              <Route path="/reports/:date" element={<ReportPage />} />
              <Route path="/trends" element={<Trends />} />
              <Route path="/learnings" element={<Placeholder title="Learnings" />} />
              <Route path="/ads" element={<Placeholder title="Ads" />} />
              <Route path="/agent" element={<Agent />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/more" element={<More />} />
              <Route path="/assets/:id" element={<AssetPage />} />
              <Route path="*" element={<Placeholder title="Not found" />} />
            </Routes>
          </main>
        </div>

        <nav aria-label="Tabs"
          className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-line bg-surface/90 pr-[env(safe-area-inset-right)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] backdrop-blur-md lg:hidden">
          {NAV.filter((n) => n.tab).map(({ path, label, Icon }) => (
            <NavLink key={path} to={path} className={({ isActive }) => tabLink(isActive)}>
              {({ isActive }) => <>{tabIcon(Icon, isActive)}{label}</>}
            </NavLink>
          ))}
          <Link to="/more" aria-current={inMore ? 'page' : undefined} className={tabLink(inMore)}>
            {tabIcon(MoreIcon, inMore)}More
          </Link>
        </nav>
      </div>
    </ToastProvider>
  )
}

/** The phone's "More" tab: the pages that have no tab of their own. */
function More() {
  return (
    <>
      <PageHeader title="More" />
      <ul className={`${card} divide-y divide-line/60 overflow-hidden`}>
        {MORE.map(({ path, label, Icon }) => (
          <li key={path}>
            <Link to={path} className="flex min-h-14 items-center gap-3 px-4 font-medium hover:bg-surface-2">
              <Icon className="text-muted" /><span className="flex-1">{label}</span><ChevronIcon className="text-muted" />
            </Link>
          </li>
        ))}
      </ul>
    </>
  )
}
