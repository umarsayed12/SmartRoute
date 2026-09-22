// Display measured gateway savings, routing distribution, feedback, and latency.
import { useEffect, useState } from 'react'
import { ArrowUpRight, BrainCircuit, CircleDollarSign, LoaderCircle, MessageSquare, RefreshCw, ThumbsUp } from 'lucide-react'
import { api } from '../api'
import type { Stats } from '../types'
import { formatCost, formatLatency } from '../format'
import KpiCard from '../components/KpiCard'
import TierBadge from '../components/TierBadge'
import TierPie from '../components/charts/TierPie'
import QualityBar from '../components/charts/QualityBar'
import SavingsLine from '../components/charts/SavingsLine'
import ui from './Workspace.module.css'
import styles from './Dashboard.module.css'

export default function Dashboard() {
  const [days, setDays] = useState(7)
  const [revision, setRevision] = useState(0)
  const [data, setData] = useState<Stats | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    api.stats(days, controller.signal).then((result) => {
      if (!controller.signal.aborted) setData(result)
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Statistics could not be loaded.')
    })
    return () => controller.abort()
  }, [days, revision])

  function refresh(nextDays = days) {
    setData(null)
    setError('')
    setDays(nextDays)
    setRevision((value) => value + 1)
  }

  return <div className={ui.page}>
    <div className={ui.toolbar}><h2>Gateway overview</h2><div className={ui.actions}>
      <select className={ui.select} aria-label="Dashboard period" value={days} onChange={(event) => refresh(Number(event.target.value))}>{[7, 14, 30].map((value) => <option key={value} value={value}>Last {value} days</option>)}</select>
      <button type="button" className={ui.iconButton} aria-label="Refresh dashboard" title="Refresh dashboard" onClick={() => refresh()}><RefreshCw size={15} /></button>
    </div></div>
    {error && <div className={ui.error} role="alert">{error}<button className={ui.button} type="button" onClick={() => refresh()}>Retry</button></div>}
    {!data && !error && <div className={ui.loading} role="status"><LoaderCircle className={ui.spinner} size={20} />Loading statistics</div>}
    {data && <>
      <div className={styles.kpis}>
        <KpiCard label="Requests" value={data.totals.requests.toLocaleString()} detail={`${days} UTC calendar days`} icon={MessageSquare} />
        <KpiCard label="Saved" value={formatCost(data.cost.saved_usd)} detail={`${data.cost.saved_pct.toFixed(1)}% vs reference`} icon={CircleDollarSign} accent />
        <KpiCard label="Escalation rate" value={`${(data.totals.escalation_rate * 100).toFixed(1)}%`} detail={`${data.totals.escalations} escalations`} icon={ArrowUpRight} />
        <KpiCard label="Positive feedback" value={data.quality.positive_rate === null ? 'N/A' : `${(data.quality.positive_rate * 100).toFixed(1)}%`} detail={`${data.quality.feedback_count} rated answers`} icon={ThumbsUp} />
        <KpiCard label="Learned share" value={`${(data.totals.requests ? data.routing_modes.learned / data.totals.requests * 100 : 0).toFixed(1)}%`} detail={`${data.routing_modes.learned} learned decisions`} icon={BrainCircuit} />
      </div>
      <div className={styles.chartGrid}>
        <section className={ui.section}><h2 className={ui.sectionTitle}>Final tier distribution</h2><TierPie distribution={data.tier_distribution} /></section>
        <section className={ui.section}><h2 className={ui.sectionTitle}>Positive feedback by tier</h2><QualityBar quality={data.quality.by_tier} /></section>
      </div>
      <section className={ui.section}><h2 className={ui.sectionTitle}>Savings and feedback</h2><SavingsLine timeline={data.timeline} /></section>
      <section className={ui.section}><h2 className={ui.sectionTitle}>Routing latency</h2><div className={ui.tableWrap}><table className={ui.table}><thead><tr><th>Final tier</th><th>Requests</th><th>p50</th><th>p95</th></tr></thead><tbody>
        {(['small', 'medium', 'large'] as const).map((tier) => <tr key={tier}><td><TierBadge tier={tier} /></td><td className={ui.mono}>{data.tier_distribution[tier]}</td><td className={ui.mono}>{data.latency[tier].p50 === null ? 'N/A' : formatLatency(data.latency[tier].p50)}</td><td className={ui.mono}>{data.latency[tier].p95 === null ? 'N/A' : formatLatency(data.latency[tier].p95)}</td></tr>)}
      </tbody></table></div></section>
    </>}
  </div>
}