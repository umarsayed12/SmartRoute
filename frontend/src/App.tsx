// Provide the responsive five-route workspace shell and live gateway status.
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Boxes, ChevronRight, Code2, FlaskConical, KeyRound, LayoutDashboard, ListFilter, LogOut, Menu, MessageSquare, RefreshCw, Route, Settings2, X } from 'lucide-react'
import { Link, NavLink, Navigate, Route as PageRoute, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth'
import type { Health, Tier } from './types'
import Playground from './pages/Playground'
import ModelSetupPending from './pages/ModelSetupPending'
import styles from './App.module.css'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const Requests = lazy(() => import('./pages/Requests'))
const TestLab = lazy(() => import('./pages/TestLab'))
const Settings = lazy(() => import('./pages/Settings'))
const Account = lazy(() => import('./pages/Account'))
const Models = lazy(() => import('./pages/Models'))
const Integration = lazy(() => import('./pages/Integration'))

const navigation = [
  { path: '/', label: 'Playground', icon: MessageSquare },
  { path: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { path: '/requests', label: 'Requests', icon: ListFilter },
  { path: '/testlab', label: 'Test Lab', icon: FlaskConical },
  { path: '/settings', label: 'Settings', icon: Settings2 },
]

export default function App() {
  const auth = useAuth()
  const location = useLocation()
  const pathname = location.pathname.replace(/\/+$/, '') || '/'
  const [signingOut, setSigningOut] = useState(false)
  const [signOutError, setSignOutError] = useState('')
  const [health, setHealth] = useState<Health | null>(null)
  const [tiers, setTiers] = useState<Tier[]>([])
  const [checking, setChecking] = useState(true)
  const [tierError, setTierError] = useState(false)
  const [revision, setRevision] = useState(0)
  const [hasModels, setHasModels] = useState<boolean | null>(null)
  const [setupError, setSetupError] = useState(false)
  const local = auth.config.mode === 'local'
  const verified = local || auth.account?.user?.email_verified === true
  const inferenceReady = auth.config.inference_enabled && (local || (verified && hasModels === true))
  const links = local ? navigation : [...navigation, { path: '/models', label: 'Models', icon: Boxes }, { path: '/account', label: 'API Keys', icon: KeyRound }, { path: '/integration', label: 'Integration', icon: Code2 }]
  const activePage = links.find((item) => item.path === pathname) ?? navigation[0]
  const isPlayground = pathname === '/'
  const isTestLab = pathname === '/testlab'
  const [testLabOpened, setTestLabOpened] = useState(isTestLab)
  const [menuRouteKey, setMenuRouteKey] = useState<string | null>(null)
  const menuOpen = menuRouteKey === location.key
  const mobileMenu = useRef<HTMLDialogElement>(null)
  const displayName = auth.account?.user?.display_name?.trim() || auth.account?.user?.email?.split('@')[0] || 'Account'
  const initials = displayName.split(/\s+/).slice(0, 2).map((part) => part[0]).join('').toUpperCase()

  useEffect(() => { document.title = `SmartRoute | ${activePage.label}` }, [activePage.label])

  useEffect(() => {
    const dialog = mobileMenu.current
    if (!menuOpen || !dialog) return
    dialog.showModal()
    dialog.querySelector<HTMLAnchorElement>('[aria-current="page"]')?.focus()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setMenuRouteKey(null) }
    }
    document.addEventListener('keydown', closeOnEscape, true)
    return () => { document.removeEventListener('keydown', closeOnEscape, true); dialog.close(); document.body.style.overflow = previousOverflow }
  }, [menuOpen])

  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 721px)')
    const closeOnDesktop = () => { if (desktop.matches) setMenuRouteKey(null) }
    desktop.addEventListener('change', closeOnDesktop)
    return () => desktop.removeEventListener('change', closeOnDesktop)
  }, [])

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    async function refresh() {
      setChecking(true)
      if (!local) {
        void api.models(controller.signal).then((models) => {
          if (active) { setHasModels(models.some((model) => model.enabled)); setSetupError(false) }
        }).catch(() => { if (active) setSetupError(true) })
      }
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
  }, [revision, local])

  const navigationLinks = links.map(({ path, label, icon: Icon }) => <NavLink key={path} to={path} end={path === '/'} title={label} onClick={() => { if (path === '/testlab') setTestLabOpened(true); setMenuRouteKey(null) }} className={({ isActive }) => `${styles.navLink} ${isActive ? styles.navActive : ''}`}>
    <Icon size={18} strokeWidth={1.7} /><span>{label}</span>
    {path === '/' && <span className={styles.navIndicator} />}
  </NavLink>)

  return <div className={styles.shell}>
    <a className={styles.skip} href="#workspace">Skip to workspace</a>
    <aside className={styles.sidebar}>
      <NavLink to="/" className={styles.brand} aria-label="SmartRoute home">
        <span className={styles.brandMark}><Route size={22} strokeWidth={2} /></span>
        <span>SmartRoute<span className={styles.brandDot}>.</span></span>
      </NavLink>
      <button type="button" className={styles.menuButton} title="Open navigation" aria-label="Open navigation" aria-haspopup="dialog" aria-expanded={menuOpen} aria-controls="mobile-workspace-navigation" onClick={() => setMenuRouteKey(location.key)}><Menu size={22} /></button>
      <div className={styles.navCaption}>WORKSPACE</div>
      <nav className={styles.navigation} aria-label="Main navigation">
        {navigationLinks}
      </nav>
      <div className={styles.sidebarBottom}>
        <div className={styles.connection}>
          <span className={`${styles.statusDot} ${health ? styles.online : checking ? styles.connecting : styles.offline}`} />
          <div><strong>{health ? 'Gateway online' : checking ? 'Connecting' : 'Gateway offline'}</strong><span>{auth.config.mode !== 'local' ? 'Private workspace' : health && !health.ollama ? 'Ollama unavailable' : 'localhost:8000'}</span></div>
          <button type="button" className={styles.refresh} title="Refresh connection" aria-label="Refresh connection" onClick={() => setRevision((value) => value + 1)} disabled={checking}><RefreshCw size={14} className={checking ? styles.spinning : ''} /></button>
        </div>
        <div className={styles.footer}><span>{local ? 'LOCAL WORKSPACE' : auth.config.mode === 'hosted' ? 'PRIVATE WORKSPACE' : 'AUTHENTICATED PREVIEW'}</span><a href="https://github.com/umarsayed12/SmartRoute" target="_blank" rel="noreferrer" aria-label="SmartRoute on GitHub" title="GitHub repository"><ArrowUpRight size={15} /></a></div>
      </div>
    </aside>
    <dialog ref={mobileMenu} id="mobile-workspace-navigation" className={styles.mobileMenu} aria-labelledby="mobile-navigation-title" onCancel={(event) => { event.preventDefault(); setMenuRouteKey(null) }} onClose={() => setMenuRouteKey(null)} onClick={(event) => {
      if (event.target !== event.currentTarget) return
      const bounds = event.currentTarget.getBoundingClientRect()
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) setMenuRouteKey(null)
    }}>
      <div className={styles.mobileMenuHeader}><h2 id="mobile-navigation-title">Workspace</h2><button type="button" className={styles.menuClose} title="Close navigation" aria-label="Close navigation" onClick={() => setMenuRouteKey(null)}><X size={20} /></button></div>
      <nav className={styles.mobileNavigation} aria-label="Mobile navigation">{navigationLinks}</nav>
      <div className={styles.mobileConnection}><span className={`${styles.statusDot} ${health ? styles.online : checking ? styles.connecting : styles.offline}`} /><span>{health ? 'Gateway online' : checking ? 'Connecting' : 'Gateway offline'}</span><button type="button" className={styles.menuClose} title="Refresh connection" aria-label="Refresh connection" disabled={checking} onClick={() => setRevision((value) => value + 1)}><RefreshCw size={16} className={checking ? styles.spinning : ''} /></button></div>
    </dialog>
    <main id="workspace" className={styles.main}>
      <header className={styles.pageHeader}>
        <div><div className={styles.breadcrumb}>Workspace<ChevronRight size={12} /><span>{activePage.label}</span></div><h1>{activePage.label}</h1></div>
        <div className={styles.headerActions}>{auth.config.mode !== 'hosted' && <a className={styles.apiLink} href="/docs" target="_blank" rel="noreferrer" title="Backend API reference"><span>API reference</span><ArrowUpRight size={15} /></a>}{auth.account && <><Link to="/account" className={styles.userIdentity} title={displayName} aria-label={`Account: ${displayName}`}><span className={styles.avatar} aria-hidden="true">{initials}</span><span className={styles.userName}>{displayName}</span></Link><button type="button" className={styles.refresh} aria-label="Sign out" title="Sign out" disabled={signingOut} onClick={() => { setSigningOut(true); void auth.signOut().catch(() => setSignOutError('Sign-out failed. Try again.')).finally(() => setSigningOut(false)) }}><LogOut size={17} /></button></>}</div>
      </header>
      {signOutError && <div className={styles.authError} role="alert">{signOutError}</div>}
      <div className={styles.stage} hidden={!isPlayground}>
        {inferenceReady ? <Playground tiers={tiers} tierError={tierError} visible={isPlayground} /> : <ModelSetupPending verified={verified} loading={hasModels === null && !setupError && verified} error={setupError} onRetry={() => setRevision((value) => value + 1)} />}
      </div>
      <div className={styles.stage} hidden={!isTestLab}>
        {(testLabOpened || isTestLab) && (inferenceReady ? <Suspense fallback={<div className={styles.routeLoading} role="status">Loading Test Lab</div>}><TestLab visible={isTestLab} /></Suspense> : <ModelSetupPending verified={verified} loading={hasModels === null && !setupError && verified} error={setupError} onRetry={() => setRevision((value) => value + 1)} />)}
      </div>
      <Suspense fallback={<div className={styles.routeLoading} role="status">Loading workspace</div>}><Routes>
        <PageRoute path="/" element={null} />
        <PageRoute path="/dashboard" element={<Dashboard />} />
        <PageRoute path="/requests" element={<Requests />} />
        <PageRoute path="/testlab" element={null} />
        <PageRoute path="/settings" element={<Settings />} />
        {auth.config.mode !== 'local' && <PageRoute path="/account" element={<Account />} />}
        {!local && <PageRoute path="/models" element={<Models onChanged={() => setRevision((value) => value + 1)} />} />}
        {!local && <PageRoute path="/integration" element={<Integration modelsReady={hasModels} onRefresh={() => setRevision((value) => value + 1)} />} />}
        <PageRoute path="*" element={<Navigate to="/" replace />} />
      </Routes></Suspense>
    </main>
  </div>
}
