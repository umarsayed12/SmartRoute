// Inspect one complete request and update its historical feedback in a modal drawer.
import { useEffect, useRef, useState } from 'react'
import { Check, LoaderCircle, Save, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import { api } from '../api'
import { formatCost, formatLatency } from '../format'
import type { RequestDetail } from '../types'
import TierBadge from './TierBadge'
import ui from '../pages/Workspace.module.css'
import styles from './RequestDrawer.module.css'

interface Props { requestId: string; onClose: () => void; onRated: () => void }

function prettyJSON(value: string): string {
  try { return JSON.stringify(JSON.parse(value), null, 2) } catch { return value }
}

export default function RequestDrawer({ requestId, onClose, onRated }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const writing = useRef<AbortController | null>(null)
  const [record, setRecord] = useState<RequestDetail | null>(null)
  const [error, setError] = useState('')
  const [score, setScore] = useState<1 | -1 | null>(null)
  const [note, setNote] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => { writing.current?.abort(); element?.close() }
  }, [])

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') { event.preventDefault(); onClose() }
    }
    document.addEventListener('keydown', closeOnEscape, true)
    return () => document.removeEventListener('keydown', closeOnEscape, true)
  }, [onClose])

  useEffect(() => {
    const controller = new AbortController()
    api.request(requestId, controller.signal).then((result) => {
      if (controller.signal.aborted) return
      setRecord(result)
      setScore(result.feedback)
      setNote(result.feedback_note ?? '')
    }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Request details could not be loaded.')
    })
    return () => controller.abort()
  }, [requestId, revision])

  async function saveFeedback() {
    if (score === null || writing.current) return
    const controller = new AbortController()
    writing.current = controller
    setSaving(true)
    setSaved(false)
    setError('')
    try {
      const result = await api.feedback(requestId, score, note.trim(), controller.signal)
      if (controller.signal.aborted) return
      setRecord((current) => current ? { ...current, feedback: result.score, feedback_note: result.note } : current)
      setSaved(true)
      onRated()
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Feedback could not be saved.')
    } finally {
      writing.current = null
      if (!controller.signal.aborted) setSaving(false)
    }
  }

  return <dialog ref={dialog} className={styles.drawer} aria-labelledby="request-detail-title" onCancel={(event) => { event.preventDefault(); onClose() }} onClick={(event) => {
    if (event.target === event.currentTarget) {
      const bounds = event.currentTarget.getBoundingClientRect()
      if (event.clientX < bounds.left || event.clientX > bounds.right) onClose()
    }
  }}>
    <header className={styles.header}><div><h2 id="request-detail-title">Request details</h2><span className={ui.mono}>{requestId}</span></div><button type="button" className={ui.iconButton} aria-label="Close request details" title="Close request details" onClick={onClose}><X size={17} /></button></header>
    <div className={styles.body}>
      {error && <div className={ui.error} role="alert">{error}{!record && <button type="button" className={ui.button} onClick={() => { setError(''); setRevision((value) => value + 1) }}>Retry</button>}</div>}
      {!record && !error && <div className={ui.loading} role="status"><LoaderCircle className={ui.spinner} size={20} />Loading request</div>}
      {record && <>
        <div className={ui.row}><TierBadge tier={record.tier_final} /><span className={ui.muted}>{record.routing_mode}</span>{record.escalated && <span className={styles.escalated}>Escalated</span>}<span className={styles.source}>{record.source}</span></div>
        <dl className={styles.facts}><div><dt>Created</dt><dd>{new Date(record.created_at).toLocaleString()}</dd></div><div><dt>Confidence</dt><dd>{Math.round(record.confidence * 100)}%</dd></div><div><dt>Chosen tier</dt><dd>{record.tier_chosen}</dd></div><div><dt>Routing latency</dt><dd>{formatLatency(record.latency_ms)}</dd></div></dl>
        <section className={ui.section}><h3 className={ui.sectionTitle}>Routing reason</h3><p className={styles.reason}>{record.reason}</p></section>
        <section className={ui.section}><h3 className={ui.sectionTitle}>Full conversation</h3><pre className={styles.content}>{prettyJSON(record.prompt_full)}</pre></section>
        <section className={ui.section}><h3 className={ui.sectionTitle}>Full answer</h3><pre className={styles.content}>{record.answer_full}</pre></section>
        <section className={ui.section}><h3 className={ui.sectionTitle}>Cost breakdown</h3><dl className={styles.facts}>
          <div><dt>Actual</dt><dd>{formatCost(record.actual_cost_usd)}</dd></div><div><dt>Reference</dt><dd>{formatCost(record.reference_cost_usd)}</dd></div><div><dt>Saved</dt><dd>{formatCost(record.reference_cost_usd - record.actual_cost_usd)}</dd></div><div><dt>Input / output tokens</dt><dd>{record.prompt_tokens} / {record.completion_tokens}</dd></div>
        </dl></section>
        <details className={ui.section}><summary className={styles.summary}>Feature vector</summary><pre className={styles.content}>{prettyJSON(record.features_json)}</pre></details>
        <section className={ui.section}><h3 className={ui.sectionTitle}>Feedback</h3><form onSubmit={(event) => { event.preventDefault(); void saveFeedback() }}>
          <div className={ui.actions}><button type="button" className={`${ui.button} ${score === 1 ? styles.chosen : ''}`} aria-pressed={score === 1} disabled={saving} onClick={() => { setScore(1); setSaved(false) }}><ThumbsUp size={14} />Positive</button><button type="button" className={`${ui.button} ${score === -1 ? styles.chosen : ''}`} aria-pressed={score === -1} disabled={saving} onClick={() => { setScore(-1); setSaved(false) }}><ThumbsDown size={14} />Negative</button></div>
          <label className={`${ui.field} ${styles.note}`}>Feedback note (optional)<textarea rows={3} value={note} disabled={saving} onChange={(event) => { setNote(event.target.value); setSaved(false) }} /></label>
          <div className={ui.actions}><button type="submit" className={ui.primary} disabled={score === null || saving}>{saving ? <LoaderCircle size={14} className={ui.spinner} /> : <Save size={14} />}Save feedback</button>{saved && <span className={ui.success} role="status"><Check size={14} />Feedback saved</span>}</div>
        </form></section>
      </>}
    </div>
  </dialog>
}