// Edit persisted routing settings and inspect provider health and real training reports.
import { useEffect, useRef, useState } from 'react'
import { BrainCircuit, Check, LoaderCircle, RefreshCw, RotateCcw, Save, X } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { formatCost } from '../format'
import type { Health, RuntimeSettings, Tier, TrainingResult, TrainingStatus } from '../types'
import DataTable from '../components/DataTable'
import type { Column } from '../components/DataTable'
import TierBadge from '../components/TierBadge'
import ui from './Workspace.module.css'
import styles from './Settings.module.css'

type Draft = { [Key in keyof RuntimeSettings]: string }

function makeDraft(values: RuntimeSettings): Draft {
  return Object.fromEntries(Object.entries(values).map(([name, value]) => [name, String(value)])) as Draft
}

function parseDraft(draft: Draft): RuntimeSettings {
  return {
    confidence_threshold: Number(draft.confidence_threshold),
    max_escalations: Number(draft.max_escalations),
    reference_input_price_per_1k: Number(draft.reference_input_price_per_1k),
    reference_output_price_per_1k: Number(draft.reference_output_price_per_1k),
    routing_mode_preference: draft.routing_mode_preference as RuntimeSettings['routing_mode_preference'],
  }
}

export default function Settings() {
  const auth = useAuth()
  const [baseline, setBaseline] = useState<RuntimeSettings | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [tiers, setTiers] = useState<Tier[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [status, setStatus] = useState<TrainingStatus | null>(null)
  const [trainingResult, setTrainingResult] = useState<TrainingResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [training, setTraining] = useState(false)
  const [saved, setSaved] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [saveError, setSaveError] = useState('')
  const [trainError, setTrainError] = useState('')
  const [revision, setRevision] = useState(0)
  const saveController = useRef<AbortController | null>(null)
  const trainController = useRef<AbortController | null>(null)
  const values = draft ? parseDraft(draft) : null
  const valid = Boolean(values && draft &&
    [draft.confidence_threshold, draft.max_escalations, draft.reference_input_price_per_1k, draft.reference_output_price_per_1k].every((value) => value.trim() && Number.isFinite(Number(value))) &&
    values.confidence_threshold >= 0 && values.confidence_threshold <= 1 && Number.isInteger(values.max_escalations) && values.max_escalations >= 0 &&
    values.reference_input_price_per_1k >= 0 && values.reference_output_price_per_1k >= 0)
  const dirty = Boolean(values && baseline && (Object.keys(values) as (keyof RuntimeSettings)[]).some((name) => values[name] !== baseline[name]))
  const metadata = status?.trained ? status : null

  useEffect(() => () => { saveController.current?.abort(); trainController.current?.abort() }, [])
  useEffect(() => {
    const controller = new AbortController()
    Promise.allSettled([api.settings(controller.signal), api.tiers(controller.signal), api.health(controller.signal), api.trainingStatus(controller.signal)]).then(([settingsResult, tiersResult, healthResult, statusResult]) => {
      if (controller.signal.aborted) return
      if (settingsResult.status === 'fulfilled') { setBaseline(settingsResult.value); setDraft(makeDraft(settingsResult.value)) }
      else { setBaseline(null); setDraft(null) }
      setTiers(tiersResult.status === 'fulfilled' ? tiersResult.value : [])
      setHealth(healthResult.status === 'fulfilled' ? healthResult.value : null)
      setStatus(statusResult.status === 'fulfilled' ? statusResult.value : null)
      const failures = [settingsResult, tiersResult, healthResult, statusResult].filter((result) => result.status === 'rejected')
      if (failures.length) setLoadError('Some gateway settings or status information could not be loaded.')
      setLoading(false)
    })
    return () => controller.abort()
  }, [revision])

  function edit(name: keyof Draft, value: string) {
    setDraft((current) => current ? { ...current, [name]: value } : current)
    setSaved(false)
    setSaveError('')
  }

  function refresh() { setLoading(true); setLoadError(''); setSaved(false); setRevision((value) => value + 1) }

  async function saveSettings() {
    if (!values || !valid || !dirty || saveController.current) return
    const controller = new AbortController()
    saveController.current = controller
    setSaving(true)
    setSaveError('')
    try {
      const result = await api.updateSettings(values, controller.signal)
      if (controller.signal.aborted) return
      setBaseline(result)
      setDraft(makeDraft(result))
      setSaved(true)
    } catch (failure) {
      if (!controller.signal.aborted) setSaveError(failure instanceof Error ? failure.message : 'Settings could not be saved.')
    } finally {
      saveController.current = null
      if (!controller.signal.aborted) setSaving(false)
    }
  }

  async function retrain() {
    if (trainController.current) return
    const controller = new AbortController()
    trainController.current = controller
    setTraining(true)
    setTrainError('')
    setTrainingResult(null)
    try {
      const result = await api.train(controller.signal)
      if (controller.signal.aborted) return
      setTrainingResult(result)
      const [latestStatus, latestHealth] = await Promise.allSettled([api.trainingStatus(controller.signal), api.health(controller.signal)])
      if (controller.signal.aborted) return
      if (latestStatus.status === 'fulfilled') setStatus(latestStatus.value)
      if (latestHealth.status === 'fulfilled') setHealth(latestHealth.value)
    } catch (failure) {
      if (!controller.signal.aborted) setTrainError(failure instanceof Error ? failure.message : 'Training failed.')
    } finally {
      trainController.current = null
      if (!controller.signal.aborted) setTraining(false)
    }
  }

  const columns: Column<Tier>[] = [
    { id: 'tier', label: 'Tier', render: (tier) => <TierBadge tier={tier.name} /> },
    { id: 'model', label: 'Model', render: (tier) => <span className={ui.mono}>{tier.model || 'Not configured'}</span> },
    { id: 'provider', label: 'Provider', render: (tier) => <span className={ui.muted}>{tier.provider === 'ollama' ? 'Ollama' : 'OpenAI-compatible'}</span> },
    { id: 'input', label: 'Input / 1k', render: (tier) => <span className={ui.mono}>{formatCost(tier.input_price_per_1k)}</span> },
    { id: 'output', label: 'Output / 1k', render: (tier) => <span className={ui.mono}>{formatCost(tier.output_price_per_1k)}</span> },
    { id: 'status', label: 'Availability', render: (tier) => <span className={`${ui.row} ${!tier.enabled ? ui.muted : tier.reachable ? ui.good : ui.bad}`}>{tier.enabled ? <>{tier.reachable ? <Check size={14} /> : <X size={14} />}{tier.reachable ? 'Reachable' : 'Unreachable'}</> : 'Disabled'}</span> },
  ]
  const checks = [
    { name: 'Backend', state: health ? health.status === 'ok' : null, yes: 'Online', no: 'Unavailable' },
    ...(auth.config.mode === 'local' ? [{ name: 'Ollama', state: health?.ollama ?? null, yes: 'Reachable', no: 'Unavailable' }] : []),
    { name: 'Model file', state: health?.model_file_present ?? null, yes: 'Present', no: 'Not detected' },
  ]

  return <div className={ui.page}>
    <div className={ui.toolbar}><h2>Gateway configuration</h2><button type="button" className={ui.iconButton} aria-label="Refresh settings" title="Refresh settings" disabled={loading || saving || training || dirty} onClick={refresh}><RefreshCw size={15} /></button></div>
    {loadError && <div className={ui.error} role="alert">{loadError}<button type="button" className={ui.button} disabled={dirty || saving || training} onClick={refresh}>Retry</button></div>}
    {loading && !draft && <div className={ui.loading} role="status"><LoaderCircle className={ui.spinner} size={20} />Loading configuration</div>}
    <section><h2 className={ui.sectionTitle}>Model tiers</h2><DataTable rows={tiers} columns={columns} rowKey={(tier) => tier.name} label="Model tier configuration" emptyText={loading ? 'Checking models' : auth.config.mode === 'local' ? 'Tier status unavailable' : 'No models configured'} /></section>
    <div className={styles.configuration}>
      <section className={ui.section}><h2 className={ui.sectionTitle}>Routing policy</h2>{draft && <form onSubmit={(event) => { event.preventDefault(); void saveSettings() }}>
        <fieldset className={styles.formFields} disabled={saving || loading}>
          <label className={ui.field}><span className={styles.rangeLabel}>Confidence threshold <strong>{Math.round(Number(draft.confidence_threshold) * 100)}%</strong></span><input aria-label="Confidence threshold" type="range" min={0} max={1} step={0.01} value={draft.confidence_threshold} onChange={(event) => edit('confidence_threshold', event.target.value)} /></label>
          <label className={ui.field}>Max escalations<input type="number" min={0} step={1} required value={draft.max_escalations} onChange={(event) => edit('max_escalations', event.target.value)} /></label>
          <div className={styles.prices}><label className={ui.field}>Reference input / 1k (USD)<input type="number" min={0} step="any" required value={draft.reference_input_price_per_1k} onChange={(event) => edit('reference_input_price_per_1k', event.target.value)} /></label><label className={ui.field}>Reference output / 1k (USD)<input type="number" min={0} step="any" required value={draft.reference_output_price_per_1k} onChange={(event) => edit('reference_output_price_per_1k', event.target.value)} /></label></div>
          <fieldset className={styles.policy}><legend>Routing preference</legend><div className={styles.policyOptions}>{[['auto', 'Auto'], ['heuristic_only', 'Heuristic only'], ['learned_only', 'Learned only']].map(([value, label]) => <label key={value}><input type="radio" name="routing-preference" value={value} checked={draft.routing_mode_preference === value} onChange={() => edit('routing_mode_preference', value)} /><span>{label}</span></label>)}</div></fieldset>
        </fieldset>
        {!valid && <p className={ui.bad}>Use whole-number escalations and non-negative prices.</p>}
        {saveError && <div className={ui.error} role="alert">{saveError}</div>}
        <div className={ui.actions}><button type="submit" className={ui.primary} disabled={!dirty || !valid || saving || loading}>{saving ? <LoaderCircle className={ui.spinner} size={15} /> : <Save size={15} />}Save settings</button><button type="button" className={ui.button} disabled={!dirty || saving || !baseline} onClick={() => { if (baseline) setDraft(makeDraft(baseline)); setSaved(false); setSaveError('') }}><RotateCcw size={14} />Reset edits</button>{saved ? <span className={ui.success} role="status"><Check size={14} />Settings saved</span> : dirty && <span className={ui.muted}>Unsaved changes</span>}</div>
      </form>}</section>
      <section className={ui.section}><h2 className={ui.sectionTitle}>Health</h2><dl className={styles.health}>{checks.map((check) => <div key={check.name}><dt>{check.name}</dt><dd className={check.state === null ? ui.muted : check.state ? ui.good : ui.bad}>{check.state === null ? 'Unknown' : <>{check.state ? <Check size={14} /> : <X size={14} />}{check.state ? check.yes : check.no}</>}</dd></div>)}{auth.config.retention_days && <div><dt>Request retention</dt><dd>{auth.config.retention_days} days</dd></div>}</dl></section>
    </div>
    <section className={ui.section}><div className={ui.toolbar}><h2>Learned router</h2><button type="button" className={ui.primary} disabled={training || loading} onClick={() => void retrain()}>{training ? <LoaderCircle className={ui.spinner} size={15} /> : <BrainCircuit size={16} />}{training ? 'Training router' : 'Retrain router'}</button></div>
      {trainError && <div className={ui.error} role="alert">{trainError}</div>}
      {trainingResult && !trainingResult.trained && <p className={styles.trainingNotice} role="status">{trainingResult.message}</p>}
      {trainingResult?.trained && <p className={ui.success} role="status"><Check size={14} />Training complete</p>}
      {metadata ? <><dl className={styles.trainingFacts}><div><dt>Last trained</dt><dd>{new Date(metadata.trained_at).toLocaleString()}</dd></div><div><dt>Labelled rows</dt><dd>{metadata.n_rows}</dd></div><div><dt>Accuracy</dt><dd>{(metadata.accuracy * 100).toFixed(1)}%</dd></div><div><dt>Evaluation</dt><dd>{metadata.evaluation === 'holdout' ? 'Holdout' : metadata.evaluation === 'training' ? 'Training set' : 'Not recorded'}</dd></div></dl>
        {metadata.confusion_matrix.length === metadata.classes.length && metadata.confusion_matrix.every((row) => row.length === metadata.classes.length) ? <div className={styles.matrix}><h3 className={ui.sectionTitle}>Confusion matrix</h3><div className={ui.tableWrap}><table className={ui.table} aria-label="Training confusion matrix"><thead><tr><th>Actual / predicted</th>{metadata.classes.map((tier) => <th key={tier}>{tier}</th>)}</tr></thead><tbody>{metadata.classes.map((tier, index) => <tr key={tier}><td>{tier}</td>{metadata.confusion_matrix[index].map((count, column) => <td key={metadata.classes[column]} className={column === index ? ui.good : ui.mono}>{count}</td>)}</tr>)}</tbody></table></div></div> : <p className={ui.muted}>Confusion matrix unavailable</p>}
      </> : <p className={ui.muted}>{status ? 'No trained router report' : 'Training status unavailable'}</p>}
    </section>
  </div>
}