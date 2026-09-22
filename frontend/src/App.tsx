// Provide the responsive five-route workspace shell and live gateway status.
import { useEffect, useState } from 'react'
import { ArrowUpRight, ChevronRight, FlaskConical, LayoutDashboard, ListFilter, MessageSquare, RefreshCw, Route, Settings2 } from 'lucide-react'
import { NavLink, Navigate, Route as PageRoute, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import type { Health, Tier } from './types'
import Playground from './pages/Playground'
import PlannedPage from './pages/PlannedPage'
import styles from './App.module.css'

const navigation = [
  { path: '/', label: 'Playground', icon: MessageSquare },
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/requests', label: 'Requests', icon: ListFilter },
  { path: '/testlab', label: 'Test Lab', icon: FlaskConical },
  { path: '/settings', label: 'Settings', icon: Settings2 },
]

export default function App() {
  const location = useLocation()
  const [health, setHealth] = useState<Health | null>(null)
  const [tiers, setTiers] = useState<Tier[]>([])
  const [checking, setChecking] = useState(true)
  const [tierError, setTierError] = useState(false)
  const [revision, setRevision] = useState(0)
  const activePage = navigation.find((item) => item.path === location.pathname) ?? navigation[0]
  const isPlayground = location.pathname === '/'

  useEffect(() => { document.title = `SmartRoute | ${activePage.label}` }, [activePage.label])

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    async function refresh() {
      setChecking(true)
      const [healthResult, tierResult] = await Promise.allSettled([
        api.health(controller.signal), api.tiers(controller.signal),
      ])
      if (!active) return
      setHealth(healthResult.status === 'fulfilled' ? healthResult.value : null)
      setTiers(tierResult.status === 'fulfilled' ? tierResult.value : [])
      setTierError(tierResult.status === 'rejected')
      setChecking(false)
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 30000)
    return () => { active = false; controller.abort(); window.clearInterval(timer) }
  }, [revision])

  return <div className={styles.shell}>
    <a className={styles.skip} href="#workspace">Skip to workspace</a>
    <aside className={styles.sidebar}>
      <NavLink to="/" className={styles.brand} aria-label="SmartRoute home">
        <span className={styles.brandMark}><Route size={22} strokeWidth={2} /></span>
        <span>SmartRoute<span className={styles.brandDot}>.</span></span>
      </NavLink>
      <div className={styles.navCaption}>WORKSPACE</div>
      <nav className={styles.navigation} aria-label="Main navigation">
        {navigation.map(({ path, label, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} title={label} className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navActive : ''}`}>
          <Icon size={18} strokeWidth={1.7} /><span>{label}</span>
          {path === '/' && <span className={styles.navIndicator} />}
        </NavLink>)}
      </nav>
      <div className={styles.sidebarBottom}>
        <div className={styles.connection}>
          <span className={`${styles.statusDot} ${health ? styles.online : checking ? styles.connecting : styles.offline}`} />
          <div><strong>{health ? 'Gateway online' : checking ? 'Connecting' : 'Gateway offline'}</strong><span>{health && !health.ollama ? 'Ollama unavailable' : 'localhost:8000'}</span></div>
          <button type="button" className={styles.refresh} title="Refresh connection" aria-label="Refresh connection" onClick={() => setRevision((value) => value + 1)} disabled={checking}><RefreshCw size={14} className={checking ? styles.spinning : ''} /></button>
        </div>
        <div className={styles.footer}><span>LOCAL WORKSPACE</span><a href="https://github.com/umarsayed12/SmartRoute" target="_blank" rel="noreferrer" aria-label="SmartRoute on GitHub" title="GitHub repository"><ArrowUpRight size={15} /></a></div>
      </div>
    </aside>
    <main id="workspace" className={styles.main}>
      <header className={styles.pageHeader}>
        <div><div className={styles.breadcrumb}>Workspace<ChevronRight size={12} /><span>{activePage.label}</span></div><h1>{activePage.label}</h1></div>
        <a className={styles.apiLink} href="http://127.0.0.1:8000/docs" target="_blank" rel="noreferrer" title="Backend API reference"><span>API reference</span><ArrowUpRight size={15} /></a>
      </header>
      <div className={styles.stage} hidden={!isPlayground}>
        <Playground tiers={tiers} tierError={tierError} visible={isPlayground} />
      </div>
      <Routes>
        <PageRoute path="/" element={null} />
        {navigation.slice(1).map((item) => <PageRoute key={item.path} path={item.path} element={<PlannedPage title={item.label} />} />)}
        <PageRoute path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </main>
  </div>
}
