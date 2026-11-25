import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router'
import Alerts from './Alerts'
import CalendarPage from './calendar/CalendarPage'
import CreatePage from './create/CreatePage'
import AssetPage from './inbox/AssetPage'
import InboxPage from './inbox/InboxPage'
import Ads from './pages/Ads'
import Agent from './pages/Agent'
import Analytics from './pages/Analytics'
import Breakdowns from './pages/Breakdowns'
import Learnings from './pages/Learnings'
import Planning from './pages/Planning'
import Placeholder from './pages/Placeholder'
import Posts, { PostPage } from './pages/Posts'
import ReportPage from './pages/Report'
import Settings from './pages/Settings'
import Trends from './pages/Trends'
import StylesPage from './styles/StylesPage'
import TokenBanner from './TokenBanner'
import TrendingPage from './trending/TrendingPage'
import VoicesPage from './voices/VoicesPage'
import {
  AgentIcon, BulbIcon, CalendarIcon, ChartIcon, ChevronIcon, CreateIcon, InboxIcon, MegaphoneIcon, MicIcon, MoreIcon, PaletteIcon,
  PlanningIcon, SettingsIcon, TrendsIcon,
} from './ui/icons'
import { PageHeader } from './ui/PageHeader'
import { card } from './ui/styles'
import { ToastProvider } from './ui/Toast'

// `tab`: also in the phone's bottom bar; the rest sit behind "More" there.
const NAV = [
  { path: '/inbox', label: 'Inbox', Icon: InboxIcon, tab: true },
  { path: '/create', label: 'Créer', Icon: CreateIcon, tab: true },
  // 213: Planning took Agent's phone tab (owner's third task; Agent runs are rare), was 185
  { path: '/planning', label: 'Planning', Icon: PlanningIcon, tab: true },
  { path: '/trending', label: 'Trending', Icon: TrendsIcon, tab: true },
  { path: '/calendar', label: 'Calendar', Icon: CalendarIcon, tab: true },
  { path: '/analytics', label: 'Analytics', Icon: ChartIcon }, // 174: its tab went to Créer
  { path: '/learnings', label: 'Learnings', Icon: BulbIcon },
  { path: '/styles', label: 'Styles', Icon: PaletteIcon },
  { path: '/voices', label: 'Voix', Icon: MicIcon },
  { path: '/ads', label: 'Ads', Icon: MegaphoneIcon },
  { path: '/agent', label: 'Agent', Icon: AgentIcon }, // 213: behind « More » on the phone
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
          <Brand className="px-3" />
          <nav aria-label="Main" className="mt-6 flex flex-col gap-1">
            {NAV.map(({ path, label, Icon }) => (
              <NavLink key={path} to={path} className={sideLink}><Icon />{label}</NavLink>
            ))}
          </nav>
        </aside>

        <div className="min-w-0 flex-1 pb-[calc(3.5rem+env(safe-area-inset-bottom))] lg:pb-0">
          <header className="sticky top-0 z-30 flex h-[calc(3rem+env(safe-area-inset-top))] items-center justify-between border-b border-line bg-surface/90 pt-[env(safe-area-inset-top)] pr-[max(0.5rem,env(safe-area-inset-right))] pl-[max(1rem,env(safe-area-inset-left))] backdrop-blur-md lg:static lg:h-14 lg:justify-end lg:border-0 lg:bg-transparent lg:px-8 lg:pt-0 lg:backdrop-blur-none">
            <Brand className="lg:hidden" />
            <Alerts />
          </header>
          <TokenBanner />
          <main key={pathname}
            className="mx-auto w-full max-w-6xl animate-page-in pt-4 pr-[max(1rem,env(safe-area-inset-right))] pb-8 pl-[max(1rem,env(safe-area-inset-left))] lg:px-8 lg:pt-2">
            <Routes>
              <Route path="/" element={<Navigate to="/inbox" replace />} />
              <Route path="/inbox" element={<InboxPage />} />
              <Route path="/create" element={<CreatePage />} />
              <Route path="/planning" element={<Planning />} />
              <Route path="/calendar" element={<CalendarPage />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/analytics/posts" element={<Posts />} />
              <Route path="/analytics/posts/:id" element={<PostPage />} />
              <Route path="/analytics/breakdowns" element={<Breakdowns />} />
              <Route path="/reports" element={<ReportPage />} />
              <Route path="/reports/:date" element={<ReportPage />} />
              <Route path="/trending" element={<TrendingPage />} />
              <Route path="/trends" element={<Trends />} />
              <Route path="/learnings" element={<Learnings />} />
              <Route path="/styles" element={<StylesPage />} />
              <Route path="/voices" element={<VoicesPage />} />
              <Route path="/ads" element={<Ads />} />
              <Route path="/agent" element={<Agent />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/more" element={<More />} />
              <Route path="/assets/:id" element={<AssetPage />} />
              <Route path="*" element={<Placeholder title="Not found">There is no page at this address.</Placeholder>} />
            </Routes>
          </main>
        </div>

        <nav aria-label="Tabs"
          className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-6 border-t border-line bg-surface/90 pr-[env(safe-area-inset-right)] pb-[env(safe-area-inset-bottom)] pl-[env(safe-area-inset-left)] backdrop-blur-md lg:hidden">
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

function Brand({ className = '' }: { className?: string }) {
  return (
    <p className={`flex items-center gap-2 text-base font-bold tracking-tight ${className}`}>
      <span aria-hidden className="grid size-7 place-items-center rounded-lg bg-accent text-xs font-black text-on-accent">GS</span>
      Growth Studio
    </p>
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
