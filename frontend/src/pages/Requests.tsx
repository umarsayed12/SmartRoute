// Filter and page through request history, with a full-detail feedback drawer.
import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, LoaderCircle, RefreshCw, Search, X } from 'lucide-react'
import { api } from '../api'
import type { Page, RequestFilters, RequestSummary, TierName } from '../types'
import { formatCost, formatLatency } from '../format'
import DataTable from '../components/DataTable'
import type { Column } from '../components/DataTable'
import RequestDrawer from '../components/RequestDrawer'
import TierBadge from '../components/TierBadge'
import ui from './Workspace.module.css'
import styles from './Requests.module.css'

export default function Requests() {
  const [filters, setFilters] = useState<RequestFilters>({})
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [limit, setLimit] = useState(20)
  const [revision, setRevision] = useState(0)
  const [data, setData] = useState<Page<RequestSummary> | null>(null)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    api.requests({ ...filters, limit, offset }, controller.signal).then((result) => {
      if (controller.signal.aborted) return
      if (offset > 0 && offset >= result.total) {
        setOffset(Math.max(0, Math.floor((result.total - 1) / limit) * limit))
        return
      }
      setData(result)
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Request history could not be loaded.')
    })
    return () => controller.abort()
  }, [filters, limit, offset, revision])

  function reload(nextOffset = offset) {
    setData(null)
    setError('')
    setOffset(nextOffset)
    setRevision((value) => value + 1)
  }

  function filter(updates: Partial<RequestFilters>) {
    setFilters((current) => ({ ...current, ...updates }))
    reload(0)
  }

  const columns: Column<RequestSummary>[] = [
    { id: 'prompt', label: 'Prompt', render: (row) => <button type="button" className={styles.prompt} title={row.prompt_preview} aria-label={`Open request ${row.id}`} onClick={() => setSelected(row.id)}>{row.prompt_preview || '(Empty prompt)'}</button> },
    { id: 'created', label: 'Created', render: (row) => <span className={ui.muted} title={row.created_at}>{new Date(row.created_at).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</span> },
    { id: 'tier', label: 'Final tier', render: (row) => <TierBadge tier={row.tier_final} /> },
    { id: 'status', label: 'Status', render: (row) => <span className={row.status === 'failed' ? ui.bad : ui.muted}>{row.status === 'failed' ? 'Failed' : 'Completed'}</span> },
    { id: 'escalated', label: 'Escalated', render: (row) => <span className={row.escalated ? styles.escalated : ui.muted}>{row.escalated ? 'Yes' : 'No'}</span> },
    { id: 'source', label: 'Source', render: (row) => <span className={ui.muted}>{row.source}</span> },
    { id: 'latency', label: 'Latency', render: (row) => <span className={ui.mono}>{formatLatency(row.latency_ms)}</span> },
    { id: 'cost', label: 'Actual cost', render: (row) => <span className={ui.mono}>{formatCost(row.actual_cost_usd)}</span> },
    { id: 'feedback', label: 'Feedback', render: (row) => <span className={row.feedback === null ? ui.muted : row.feedback === 1 ? ui.good : ui.bad}>{row.feedback === null ? 'Unrated' : row.feedback === 1 ? 'Positive' : 'Negative'}</span> },
  ]

  return <div className={ui.page}>
    <div className={ui.toolbar}><h2>Request history</h2><button type="button" className={ui.iconButton} aria-label="Refresh requests" title="Refresh requests" onClick={() => reload()}><RefreshCw size={15} /></button></div>
    <div className={styles.filters}>
      <form className={styles.search} onSubmit={(event) => { event.preventDefault(); filter({ search: search.trim() || undefined }) }}><label className={ui.field}>Search<input aria-label="Search requests" placeholder="Prompt or answer" value={search} onChange={(event) => setSearch(event.target.value)} /></label><button type="submit" className={ui.iconButton} aria-label="Search request history" title="Search"><Search size={15} /></button></form>
      <label className={ui.field}>Tier<select value={filters.tier ?? ''} onChange={(event) => filter({ tier: event.target.value ? event.target.value as TierName : undefined })}><option value="">All tiers</option>{['small', 'medium', 'large'].map((tier) => <option key={tier}>{tier}</option>)}</select></label>
      <label className={ui.field}>Escalated<select value={filters.escalated === undefined ? '' : String(filters.escalated)} onChange={(event) => filter({ escalated: event.target.value === '' ? undefined : event.target.value === 'true' })}><option value="">All</option><option value="true">Yes</option><option value="false">No</option></select></label>
      <label className={ui.field}>Feedback<select value={filters.feedback ?? ''} onChange={(event) => filter({ feedback: event.target.value === '' ? undefined : Number(event.target.value) as -1 | 0 | 1 })}><option value="">All ratings</option><option value="1">Positive</option><option value="-1">Negative</option><option value="0">Unrated</option></select></label>
      <label className={ui.field}>Source<select value={filters.source ?? ''} onChange={(event) => filter({ source: event.target.value ? event.target.value as RequestSummary['source'] : undefined })}><option value="">All sources</option>{['api', 'playground', 'testlab', 'sdk'].map((source) => <option key={source}>{source}</option>)}</select></label>
      <button type="button" className={ui.iconButton} title="Reset filters" aria-label="Reset request filters" onClick={() => { setSearch(''); setFilters({}); reload(0) }}><X size={15} /></button>
    </div>
    {error && <div className={ui.error} role="alert">{error}<button type="button" className={ui.button} onClick={() => reload()}>Retry</button></div>}
    {!data && !error && <div className={ui.loading} role="status"><LoaderCircle className={ui.spinner} size={20} />Loading requests</div>}
    {data && <><DataTable rows={data.items} columns={columns} rowKey={(row) => row.id} label="Request history" />
      <div className={styles.pagination}><span>{data.total ? `${offset + 1}-${Math.min(offset + data.items.length, data.total)} of ${data.total}` : '0 requests'}</span><div className={ui.actions}>
        <select className={ui.select} aria-label="Requests per page" value={limit} onChange={(event) => { setLimit(Number(event.target.value)); reload(0) }}>{[20, 50, 100].map((size) => <option key={size} value={size}>{size} / page</option>)}</select>
        <button type="button" className={ui.iconButton} aria-label="Previous request page" title="Previous page" disabled={offset === 0} onClick={() => reload(Math.max(0, offset - limit))}><ChevronLeft size={16} /></button>
        <button type="button" className={ui.iconButton} aria-label="Next request page" title="Next page" disabled={offset + limit >= data.total} onClick={() => reload(offset + limit)}><ChevronRight size={16} /></button>
      </div></div>
    </>}
    {selected && <RequestDrawer key={selected} requestId={selected} onClose={() => setSelected(null)} onRated={() => reload(0)} />}
  </div>
}