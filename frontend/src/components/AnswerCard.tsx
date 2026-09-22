// Render one model answer with routing details, feedback, and comparison selection.
import { useEffect, useRef, useState } from 'react'
import { ArrowUpRight, Check, Clock3, Copy, Info, LoaderCircle, ThumbsDown, ThumbsUp, X } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { api } from '../api'
import { formatCost, formatLatency } from '../format'
import type { PlaygroundAnswer, RunMode } from '../types'
import TierBadge from './TierBadge'
import styles from './AnswerCard.module.css'

interface Props {
  answer: PlaygroundAnswer
  compare: boolean
  canSelect: boolean
  selected: boolean
  onSelect: (mode: RunMode) => void
}

export default function AnswerCard({ answer, compare, canSelect, selected, onSelect }: Props) {
  const [rating, setRating] = useState<1 | -1 | null>(null)
  const [saving, setSaving] = useState(false)
  const [noteOpen, setNoteOpen] = useState(false)
  const [note, setNote] = useState('')
  const [actionError, setActionError] = useState('')
  const [copied, setCopied] = useState(false)
  const feedbackController = useRef<AbortController | null>(null)
  const copyTimer = useRef<number>()
  const response = answer.response
  const content = response?.choices[0]?.message.content ?? ''
  const routing = response?.smartroute
  const label = answer.mode === 'auto' ? 'SmartRoute' : `${answer.mode[0].toUpperCase()}${answer.mode.slice(1)}`

  useEffect(() => () => {
    feedbackController.current?.abort()
    window.clearTimeout(copyTimer.current)
  }, [])

  async function saveFeedback(score: 1 | -1) {
    if (!response || rating || feedbackController.current) return
    const controller = new AbortController()
    feedbackController.current = controller
    setSaving(true)
    setActionError('')
    try {
      await api.feedback(response.id, score, score === -1 ? note.trim() : undefined, controller.signal)
      setRating(score)
      setNoteOpen(false)
    } catch (error) {
      if (!controller.signal.aborted) setActionError(error instanceof Error ? error.message : 'Feedback could not be saved.')
    } finally {
      feedbackController.current = null
      if (!controller.signal.aborted) setSaving(false)
    }
  }

  async function copyAnswer() {
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      window.clearTimeout(copyTimer.current)
      copyTimer.current = window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setActionError('The answer could not be copied.')
    }
  }

  return (
    <section className={`${styles.card} ${selected ? styles.selected : ''}`} data-compare={compare} aria-label={`${label} response`}>
      <header className={styles.header}>
        <div className={styles.identity}>
          <span className={styles.name}>{label}</span>
          {response && <span className={styles.model} title={response.model}>{response.model}</span>}
        </div>
        {routing && <TierBadge tier={routing.tier_final} />}
        {!response && <span className={styles.pendingLabel}>{answer.state === 'loading' ? 'Running' : answer.state === 'queued' ? 'Queued' : answer.state === 'cancelled' ? 'Cancelled' : 'Failed'}</span>}
      </header>

      {response && routing ? (
        <>
          <div className={styles.body}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} disallowedElements={['img']} components={{
              a: ({ href, children }) => <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>,
            }}>{content}</ReactMarkdown>
          </div>
          <div className={styles.routing}>
            <span className={styles.policy}>{routing.routing_mode}</span>
            {routing.escalated && <span className={styles.escalated}><ArrowUpRight size={13} />Escalated</span>}
            {!routing.escalated && routing.tier_chosen !== routing.tier_final && <span className={styles.fallback}>Fallback</span>}
            <button type="button" className={styles.iconButton} aria-label="Routing reason" title={routing.reason}><Info size={14} /></button>
          </div>
          <dl className={styles.metrics}>
            <div><dt title="A routing signal, not a calibrated probability of correctness.">Confidence</dt><dd>{Math.round(routing.confidence * 100)}%</dd></div>
            <div><dt><Clock3 size={11} />Latency</dt><dd>{formatLatency(routing.latency_ms)}</dd></div>
            <div title={`${response.usage.prompt_tokens} input / ${response.usage.completion_tokens} output tokens`}><dt>Tokens</dt><dd>{response.usage.total_tokens.toLocaleString()}</dd></div>
          </dl>
          <div className={styles.costs}>
            <span>Actual <strong>{formatCost(routing.actual_cost_usd)}</strong></span>
            <span title="Hypothetical premium cost using the configured reference prices.">Reference <span>{formatCost(routing.reference_cost_usd)}</span></span>
          </div>
          <footer className={styles.actions}>
            <div className={styles.feedback} aria-label="Rate this answer">
              <button type="button" className={`${styles.iconButton} ${rating === 1 ? styles.rated : ''}`} disabled={saving || rating !== null} onClick={() => void saveFeedback(1)} aria-label="Rate answer positively" aria-pressed={rating === 1} title="Helpful answer"><ThumbsUp size={15} /></button>
              <button type="button" className={`${styles.iconButton} ${rating === -1 ? styles.rated : ''}`} disabled={saving || rating !== null} onClick={() => setNoteOpen(!noteOpen)} aria-label="Rate answer negatively" aria-pressed={rating === -1} title="Needs improvement"><ThumbsDown size={15} /></button>
              {saving && <LoaderCircle size={14} className={styles.spinner} aria-label="Saving feedback" />}
              {rating !== null && <span className={styles.saved}>Saved</span>}
            </div>
            <button type="button" className={styles.iconButton} onClick={() => void copyAnswer()} aria-label={copied ? 'Answer copied' : 'Copy answer'} title={copied ? 'Copied' : 'Copy answer'}>{copied ? <Check size={15} /> : <Copy size={15} />}</button>
          </footer>
          {noteOpen && <form className={styles.noteForm} onSubmit={(event) => { event.preventDefault(); void saveFeedback(-1) }}>
            <label htmlFor={`note-${response.id}`}>Feedback note <span>(optional)</span></label>
            <textarea id={`note-${response.id}`} value={note} onChange={(event) => setNote(event.target.value)} rows={2} disabled={saving} />
            <div><button type="submit" className={styles.submitFeedback} disabled={saving}>Submit feedback</button><button type="button" className={styles.iconButton} title="Cancel feedback" aria-label="Cancel feedback" disabled={saving} onClick={() => setNoteOpen(false)}><X size={15} /></button></div>
          </form>}
          {actionError && <p className={styles.error} role="alert">{actionError}</p>}
          {compare && <button type="button" className={`${styles.choose} ${selected ? styles.chosen : ''}`} onClick={() => onSelect(answer.mode)} disabled={!canSelect}>
            {selected ? <><Check size={14} />Selected</> : <>Continue with {label.toLowerCase()}<ArrowUpRight size={14} /></>}
          </button>}
        </>
      ) : answer.state === 'loading' || answer.state === 'queued' ? (
        <div className={styles.loading} role="status">
          {answer.state === 'loading' && <LoaderCircle size={18} className={styles.spinner} />}
          <span>{answer.state === 'loading' ? 'Generating answer' : 'Waiting for previous model'}</span>
          <div className={styles.skeleton}><span /><span /><span /></div>
        </div>
      ) : <div className={styles.failure} role={answer.state === 'error' ? 'alert' : 'status'}>{answer.error || 'Response cancelled.'}</div>}
    </section>
  )
}