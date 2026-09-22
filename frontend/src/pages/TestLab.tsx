// Run prompt suites and sequential comparisons while retaining completed results and history.
import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Check, ChevronLeft, ChevronRight, CircleDollarSign, Clock3, FlaskConical, Layers3, LoaderCircle, Play, RefreshCw, Target, X } from 'lucide-react'
import { api } from '../api'
import { formatCost, formatLatency } from '../format'
import type { Page, RunMode, Suite, TestLabResult, TestLabRun } from '../types'
import DataTable from '../components/DataTable'
import type { Column } from '../components/DataTable'
import KpiCard from '../components/KpiCard'
import TierBadge from '../components/TierBadge'
import RequestDrawer from '../components/RequestDrawer'
import ui from './Workspace.module.css'
import styles from './TestLab.module.css'

const modeNames: Record<RunMode, string> = { auto: 'Auto', small: 'Small-only', medium: 'Medium-only', large: 'Large-only' }
type ResultRow = TestLabResult['results'][number]

export default function TestLab({ visible }: { visible: boolean }) {
  const [suites, setSuites] = useState<Suite[]>([])
  const [suite, setSuite] = useState('default')
  const [mode, setMode] = useState<RunMode>('auto')
  const [limit, setLimit] = useState('40')
  const [history, setHistory] = useState<Page<TestLabRun> | null>(null)
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [runError, setRunError] = useState('')
  const [planned, setPlanned] = useState<RunMode[]>([])
  const [results, setResults] = useState<TestLabResult[]>([])
  const [activeResult, setActiveResult] = useState(0)
  const [running, setRunning] = useState<RunMode | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const operation = useRef<AbortController | null>(null)
  const maximum = suites.find((item) => item.id === suite)?.count ?? 40
  const parsedLimit = limit.trim() ? Number(limit) : undefined
  const validLimit = parsedLimit === undefined || (Number.isInteger(parsedLimit) && parsedLimit >= 1 && parsedLimit <= maximum)

  useEffect(() => () => operation.current?.abort(), [])
  useEffect(() => {
    if (!visible) return
    const controller = new AbortController()
    Promise.all([api.suites(controller.signal), api.runs(10, offset, controller.signal)]).then(([available, runs]) => {
      if (controller.signal.aborted) return
      setSuites(available)
      setSuite((current) => available.some((item) => item.id === current) ? current : available[0]?.id ?? '')
      setHistory(runs)
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setLoadError(failure instanceof Error ? failure.message : 'Test Lab could not be loaded.')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [visible, revision, offset])

  function refresh(nextOffset = 0) {
    setLoading(true)
    setLoadError('')
    setOffset(nextOffset)
    setRevision((value) => value + 1)
  }

  async function execute(compare: boolean) {
    if (operation.current || !validLimit || !suites.some((item) => item.id === suite)) return
    const controller = new AbortController()
    operation.current = controller
    const modes: RunMode[] = compare ? ['auto', 'large'] : [mode]
    setPlanned(modes)
    setResults([])
    setActiveResult(0)
    setRunError('')
    const completed: TestLabResult[] = []
    try {
      for (const selectedMode of modes) {
        setRunning(selectedMode)
        const result = await api.runSuite(selectedMode, parsedLimit, controller.signal, suite)
        if (controller.signal.aborted) return
        completed.push(result)
        setResults([...completed])
      }
    } catch (failure) {
      if (!controller.signal.aborted) setRunError(failure instanceof Error ? failure.message : 'The suite run failed.')
    } finally {
      operation.current = null
      if (!controller.signal.aborted) { setRunning(null); refresh() }
    }
  }

  const resultColumns: Column<ResultRow>[] = [
    { id: 'prompt', label: 'Prompt', render: (row) => <button type="button" className={styles.prompt} title={row.prompt} aria-label={`Open result ${row.id}`} onClick={() => setSelected(row.request_id)}>{row.prompt}</button> },
    { id: 'expected', label: 'Expected', render: (row) => <TierBadge tier={row.expected_tier} /> },
    { id: 'final', label: 'Final tier', render: (row) => <TierBadge tier={row.tier_final} /> },
    { id: 'match', label: 'Routing match', render: (row) => <span className={`${ui.row} ${row.match ? ui.good : ui.bad}`}>{row.match ? <Check size={13} /> : <X size={13} />}{row.match ? 'Match' : 'Mismatch'}</span> },
    { id: 'escalated', label: 'Escalated', render: (row) => row.escalated ? 'Yes' : 'No' },
    { id: 'confidence', label: 'Confidence', render: (row) => `${Math.round(row.confidence * 100)}%` },
    { id: 'latency', label: 'Latency', render: (row) => <span className={ui.mono}>{formatLatency(row.latency_ms)}</span> },
    { id: 'cost', label: 'Actual cost', render: (row) => <span className={ui.mono} title={`Reference ${formatCost(row.reference_cost_usd)}`}>{formatCost(row.actual_cost_usd)}</span> },
  ]
  const historyColumns: Column<TestLabRun>[] = [
    { id: 'date', label: 'Started', render: (row) => <span title={row.run_id}>{new Date(row.created_at).toLocaleString()}</span> },
    { id: 'mode', label: 'Mode', render: (row) => modeNames[row.mode] },
    { id: 'count', label: 'Prompts', render: (row) => row.prompt_count },
    { id: 'match', label: 'Routing match', render: (row) => `${(row.summary.routing_accuracy * 100).toFixed(1)}%` },
    { id: 'latency', label: 'Avg latency', render: (row) => formatLatency(row.summary.avg_latency_ms) },
    { id: 'cost', label: 'Actual cost', render: (row) => formatCost(row.summary.total_actual_usd) },
    { id: 'saved', label: 'Saved', render: (row) => `${row.summary.saved_pct.toFixed(1)}%` },
  ]

  return <div className={ui.page}>
    <div className={ui.toolbar}><h2>Prompt suites</h2><button className={ui.iconButton} type="button" aria-label="Refresh Test Lab" title="Refresh Test Lab" onClick={() => refresh()} disabled={loading}><RefreshCw size={15} /></button></div>
    {loadError && <div className={ui.error} role="alert">{loadError}<button type="button" className={ui.button} onClick={() => refresh()}>Retry</button></div>}
    <form className={styles.controls} onSubmit={(event) => { event.preventDefault(); void execute(false) }}>
      <label className={ui.field}>Suite<select value={suite} onChange={(event) => setSuite(event.target.value)} disabled={running !== null || !suites.length}>{!suites.length && <option value="default">Unavailable</option>}{suites.map((item) => <option key={item.id} value={item.id}>{item.name} ({item.count} prompts)</option>)}</select></label>
      <label className={ui.field}>Mode<select value={mode} onChange={(event) => setMode(event.target.value as RunMode)} disabled={running !== null}>{Object.entries(modeNames).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label className={ui.field}>Prompt limit<input type="number" min={1} max={maximum} step={1} placeholder="All" value={limit} onChange={(event) => setLimit(event.target.value)} disabled={running !== null} /></label>
      <button type="submit" className={ui.primary} disabled={running !== null || !validLimit || !suites.length}><Play size={14} />Run suite</button>
      <button type="button" className={ui.button} disabled={running !== null || !validLimit || !suites.length} onClick={() => void execute(true)}><Layers3 size={15} />Compare Auto vs Large-only</button>
    </form>
    {running && <div className={styles.progress} role="status"><LoaderCircle className={ui.spinner} size={18} /><span>Running {modeNames[running]}</span><span className={ui.mono}>{planned.indexOf(running) + 1} / {planned.length} runs</span></div>}
    {runError && <div className={ui.error} role="alert">{runError}</div>}
    {!!planned.length && <div className={planned.length > 1 ? styles.comparison : styles.summary}>
      {planned.map((plannedMode) => {
        const result = results.find((item) => item.mode === plannedMode)
        return <section key={plannedMode} className={ui.section} aria-label={`${modeNames[plannedMode]} summary`}><h3 className={ui.sectionTitle}>{modeNames[plannedMode]}{result && <span className={styles.count}>{result.prompt_count} prompts</span>}</h3>
          {result ? <><div className={styles.metrics}>
            <KpiCard label="Routing match" value={`${(result.summary.routing_accuracy * 100).toFixed(1)}%`} icon={Target} />
            <KpiCard label="Escalation rate" value={`${(result.summary.escalation_rate * 100).toFixed(1)}%`} icon={ArrowUpRight} />
            <KpiCard label="Avg latency" value={formatLatency(result.summary.avg_latency_ms)} icon={Clock3} />
            <KpiCard label="Saved" value={`${result.summary.saved_pct.toFixed(1)}%`} icon={CircleDollarSign} accent />
          </div><div className={styles.costs}><span>Actual {formatCost(result.summary.total_actual_usd)}</span><span>Reference {formatCost(result.summary.total_reference_usd)}</span></div></> : <div className={ui.empty}>{running ? 'Pending results' : 'Run not completed'}</div>}
        </section>
      })}
    </div>}
    {!!results.length && <section className={ui.section}><div className={ui.toolbar}><h2>Prompt results</h2>{results.length > 1 && <div className={styles.tabs} role="tablist" aria-label="Comparison results">{results.map((result, index) => <button key={result.run_id} type="button" role="tab" aria-selected={activeResult === index} className={activeResult === index ? styles.activeTab : ''} onClick={() => setActiveResult(index)}>{modeNames[result.mode]}</button>)}</div>}</div><DataTable rows={results[activeResult]?.results ?? []} columns={resultColumns} rowKey={(row) => row.id} label="Prompt results" /></section>}
    <section className={ui.section}><h2 className={ui.sectionTitle}>Run history</h2>{loading && !history ? <div className={ui.loading} role="status"><FlaskConical size={18} />Loading run history</div> : history && <>
      <DataTable rows={history.items} columns={historyColumns} rowKey={(row) => row.run_id} label="Test Lab run history" emptyText="No completed runs" />
      <div className={styles.pagination}><span>{history.total} completed runs</span><div className={ui.actions}><button type="button" className={ui.iconButton} title="Previous runs" aria-label="Previous runs" disabled={offset === 0 || loading} onClick={() => refresh(Math.max(0, offset - 10))}><ChevronLeft size={15} /></button><button type="button" className={ui.iconButton} title="Next runs" aria-label="Next runs" disabled={offset + 10 >= history.total || loading} onClick={() => refresh(offset + 10)}><ChevronRight size={15} /></button></div></div>
    </>}</section>
    {selected && <RequestDrawer key={selected} requestId={selected} onClose={() => setSelected(null)} onRated={() => refresh()} />}
  </div>
}