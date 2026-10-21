// Centralized data cache and state management for SmartRoute frontend.
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api'
import { useAuth } from './auth'
import type {
  ConfiguredModel, GatewayKey, Health, Page, ProviderCredential,
  RequestFilters, RequestSummary, RuntimeSettings, Stats, Suite,
  TestLabRun, Tier, TrainingStatus,
} from './types'

const STATS_TTL_MS = 60_000 // 1 minute cache for stats
const REQUESTS_TTL_MS = 30_000 // 30 seconds cache for requests

interface CachedItem<T> {
  data: T
  timestamp: number
}

export interface DataContextType {
  // Stats
  getStats: (days: number, force?: boolean) => Promise<Stats>
  cachedStats: Record<number, Stats>
  statsLoading: boolean
  statsRefreshing: boolean
  statsError: string
  invalidateStats: () => void

  // Health and Tiers (shared across App, Settings, Playground)
  health: Health | null
  tiers: Tier[]
  tierError: boolean
  checkingHealth: boolean
  refreshHealthAndTiers: () => Promise<void>

  // Models and Credentials (shared across App, Models, Integration)
  models: ConfiguredModel[] | null
  credentials: ProviderCredential[] | null
  modelsLoading: boolean
  modelsError: string
  hasEnabledModels: boolean | null
  modelsSetupError: boolean
  refreshModelsAndCredentials: () => Promise<void>
  invalidateModels: () => void

  // Runtime Settings & Training (Settings page)
  settings: RuntimeSettings | null
  trainingStatus: TrainingStatus | null
  settingsLoading: boolean
  settingsError: string
  refreshSettings: () => Promise<void>
  saveSettings: (updates: Partial<RuntimeSettings>) => Promise<RuntimeSettings>

  // API Keys (Account & Integration)
  keys: GatewayKey[] | null
  keysLoading: boolean
  keysError: string
  refreshKeys: () => Promise<void>
  invalidateKeys: () => void

  // Requests history caching (Requests page)
  getRequestsPage: (filters: RequestFilters, limit: number, offset: number, force?: boolean) => Promise<Page<RequestSummary>>
  requestsLoading: boolean
  requestsError: string
  invalidateRequests: () => void

  // Test Lab suites and runs (TestLab page)
  suites: Suite[] | null
  testLabRuns: Page<TestLabRun> | null
  testLabLoading: boolean
  testLabError: string
  getTestLabData: (offset: number, force?: boolean) => Promise<void>
  invalidateTestLab: () => void

  // Global reset
  clearAllCache: () => void
}

const DataContext = createContext<DataContextType | null>(null)

export function useData(): DataContextType {
  const context = useContext(DataContext)
  if (!context) throw new Error('useData must be used within a DataProvider')
  return context
}

export function DataProvider({ children }: { children: ReactNode }) {
  const auth = useAuth()
  const local = auth.config.mode === 'local'
  const authenticated = local || Boolean(auth.account)

  // 1. Stats State
  const statsCache = useRef<Map<number, CachedItem<Stats>>>(new Map())
  const [cachedStats, setCachedStats] = useState<Record<number, Stats>>({})
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsRefreshing, setStatsRefreshing] = useState(false)
  const [statsError, setStatsError] = useState('')

  // 2. Health & Tiers State
  const [health, setHealth] = useState<Health | null>(null)
  const [tiers, setTiers] = useState<Tier[]>([])
  const [tierError, setTierError] = useState(false)
  const [checkingHealth, setCheckingHealth] = useState(true)

  // 3. Models & Credentials State
  const [models, setModels] = useState<ConfiguredModel[] | null>(null)
  const [credentials, setCredentials] = useState<ProviderCredential[] | null>(null)
  const [modelsLoading, setModelsLoading] = useState(false)
  const [modelsError, setModelsError] = useState('')
  const [hasEnabledModels, setHasEnabledModels] = useState<boolean | null>(null)
  const [modelsSetupError, setModelsSetupError] = useState(false)

  // 4. Settings State
  const [settings, setSettings] = useState<RuntimeSettings | null>(null)
  const [trainingStatus, setTrainingStatus] = useState<TrainingStatus | null>(null)
  const [settingsLoading, setSettingsLoading] = useState(false)
  const [settingsError, setSettingsError] = useState('')

  // 5. Keys State
  const [keys, setKeys] = useState<GatewayKey[] | null>(null)
  const [keysLoading, setKeysLoading] = useState(false)
  const [keysError, setKeysError] = useState('')

  // 6. Requests Cache
  const requestsCache = useRef<Map<string, CachedItem<Page<RequestSummary>>>>(new Map())
  const [requestsLoading, setRequestsLoading] = useState(false)
  const [requestsError, setRequestsError] = useState('')

  // 7. Test Lab State
  const [suites, setSuites] = useState<Suite[] | null>(null)
  const [testLabRuns, setTestLabRuns] = useState<Page<TestLabRun> | null>(null)
  const [testLabLoading, setTestLabLoading] = useState(false)
  const [testLabError, setTestLabError] = useState('')

  // Clear caches when account or mode changes
  const clearAllCache = () => {
    statsCache.current.clear()
    requestsCache.current.clear()
    setCachedStats({})
    setModels(null)
    setCredentials(null)
    setSettings(null)
    setTrainingStatus(null)
    setKeys(null)
    setSuites(null)
    setTestLabRuns(null)
  }

  useEffect(() => {
    clearAllCache()
  }, [auth.account?.workspace.id, auth.config.mode])

  // --- Health & Tiers Poller ---
  async function refreshHealthAndTiers() {
    setCheckingHealth(true)
    try {
      const [healthResult, tiersResult] = await Promise.allSettled([api.health(), api.tiers()])
      if (healthResult.status === 'fulfilled') setHealth(healthResult.value)
      else setHealth(null)

      if (tiersResult.status === 'fulfilled') {
        setTiers(tiersResult.value)
        setTierError(false)
      } else {
        setTiers([])
        setTierError(true)
      }
    } finally {
      setCheckingHealth(false)
    }
  }

  // Poll health and tiers every 30s
  useEffect(() => {
    void refreshHealthAndTiers()
    const interval = window.setInterval(() => void refreshHealthAndTiers(), 30_000)
    return () => window.clearInterval(interval)
  }, [])

  // --- Models and Credentials ---
  async function refreshModelsAndCredentials() {
    if (local || !authenticated) return
    setModelsLoading(true)
    setModelsError('')
    try {
      const [savedCredentials, savedModels] = await Promise.all([
        api.credentials(),
        api.models(),
      ])
      setCredentials(savedCredentials)
      setModels(savedModels)
      setHasEnabledModels(savedModels.some((item) => item.enabled))
      setModelsSetupError(false)
    } catch (failure) {
      const msg = failure instanceof Error ? failure.message : 'Model configuration could not be loaded.'
      setModelsError(msg)
      setModelsSetupError(true)
    } finally {
      setModelsLoading(false)
    }
  }

  useEffect(() => {
    if (!local && authenticated) {
      void refreshModelsAndCredentials()
    }
  }, [local, authenticated])

  const invalidateModels = () => {
    void refreshModelsAndCredentials()
    void refreshHealthAndTiers()
  }

  // --- Stats Provider ---
  async function getStats(days: number, force = false): Promise<Stats> {
    const cached = statsCache.current.get(days)
    const now = Date.now()
    if (!force && cached && now - cached.timestamp < STATS_TTL_MS) {
      return cached.data
    }

    if (cached) {
      setStatsRefreshing(true)
    } else {
      setStatsLoading(true)
    }
    setStatsError('')

    try {
      const result = await api.stats(days)
      statsCache.current.set(days, { data: result, timestamp: Date.now() })
      setCachedStats((prev) => ({ ...prev, [days]: result }))
      return result
    } catch (failure) {
      const msg = failure instanceof Error ? failure.message : 'Statistics could not be loaded.'
      setStatsError(msg)
      if (cached) return cached.data
      throw failure
    } finally {
      setStatsLoading(false)
      setStatsRefreshing(false)
    }
  }

  const invalidateStats = () => {
    statsCache.current.clear()
    setCachedStats({})
  }

  // --- Settings Provider ---
  async function refreshSettings() {
    setSettingsLoading(true)
    setSettingsError('')
    try {
      const [settingsRes, trainingRes] = await Promise.allSettled([
        api.settings(),
        api.trainingStatus(),
      ])
      if (settingsRes.status === 'fulfilled') setSettings(settingsRes.value)
      if (trainingRes.status === 'fulfilled') setTrainingStatus(trainingRes.value)
    } catch (failure) {
      setSettingsError(failure instanceof Error ? failure.message : 'Settings could not be loaded.')
    } finally {
      setSettingsLoading(false)
    }
  }

  async function saveSettings(updates: Partial<RuntimeSettings>): Promise<RuntimeSettings> {
    const updated = await api.updateSettings(updates)
    setSettings(updated)
    return updated
  }

  // --- Keys Provider ---
  async function refreshKeys() {
    if (local || !authenticated) return
    setKeysLoading(true)
    setKeysError('')
    try {
      const result = await api.keys()
      setKeys(result)
    } catch (failure) {
      setKeysError(failure instanceof Error ? failure.message : 'Keys could not be loaded.')
    } finally {
      setKeysLoading(false)
    }
  }

  const invalidateKeys = () => {
    void refreshKeys()
  }

  // --- Requests Provider ---
  async function getRequestsPage(
    filters: RequestFilters, limit: number, offset: number, force = false
  ): Promise<Page<RequestSummary>> {
    const key = JSON.stringify({ ...filters, limit, offset })
    const cached = requestsCache.current.get(key)
    const now = Date.now()
    if (!force && cached && now - cached.timestamp < REQUESTS_TTL_MS) {
      return cached.data
    }

    setRequestsLoading(true)
    setRequestsError('')
    try {
      const result = await api.requests({ ...filters, limit, offset })
      requestsCache.current.set(key, { data: result, timestamp: Date.now() })
      return result
    } catch (failure) {
      const msg = failure instanceof Error ? failure.message : 'Request history could not be loaded.'
      setRequestsError(msg)
      if (cached) return cached.data
      throw failure
    } finally {
      setRequestsLoading(false)
    }
  }

  const invalidateRequests = () => {
    requestsCache.current.clear()
    invalidateStats()
  }

  // --- Test Lab Provider ---
  async function getTestLabData(offset: number, force = false): Promise<void> {
    if (!force && suites && testLabRuns && offset === 0) return
    setTestLabLoading(true)
    setTestLabError('')
    try {
      const [available, runs] = await Promise.all([
        suites ? Promise.resolve(suites) : api.suites(),
        api.runs(10, offset),
      ])
      setSuites(available)
      setTestLabRuns(runs)
    } catch (failure) {
      setTestLabError(failure instanceof Error ? failure.message : 'Test Lab could not be loaded.')
    } finally {
      setTestLabLoading(false)
    }
  }

  const invalidateTestLab = () => {
    setTestLabRuns(null)
  }

  const value: DataContextType = {
    getStats,
    cachedStats,
    statsLoading,
    statsRefreshing,
    statsError,
    invalidateStats,

    health,
    tiers,
    tierError,
    checkingHealth,
    refreshHealthAndTiers,

    models,
    credentials,
    modelsLoading,
    modelsError,
    hasEnabledModels,
    modelsSetupError,
    refreshModelsAndCredentials,
    invalidateModels,

    settings,
    trainingStatus,
    settingsLoading,
    settingsError,
    refreshSettings,
    saveSettings,

    keys,
    keysLoading,
    keysError,
    refreshKeys,
    invalidateKeys,

    getRequestsPage,
    requestsLoading,
    requestsError,
    invalidateRequests,

    suites,
    testLabRuns,
    testLabLoading,
    testLabError,
    getTestLabData,
    invalidateTestLab,

    clearAllCache,
  }

  return <DataContext.Provider value={value}>{children}</DataContext.Provider>
}
