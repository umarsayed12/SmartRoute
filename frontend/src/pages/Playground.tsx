// Manage cancellable chat turns and compare independent tier answers before continuing.
import { useEffect, useRef, useState } from 'react'
import { ArrowUp, ArrowUpRight, Braces, GitBranch, Layers3, MessageSquare, RotateCcw, Route, Square, Trash2 } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import type { ChatCompletion, ChatMessage, PlaygroundAnswer, PlaygroundMode, PlaygroundTurn, RunMode, Tier } from '../types'
import AnswerCard from '../components/AnswerCard'
import TierBadge from '../components/TierBadge'
import styles from './Playground.module.css'

const modes: { value: PlaygroundMode; label: string; accessible: string }[] = [
  { value: 'auto', label: 'Auto', accessible: 'Auto' },
  { value: 'small', label: 'Small', accessible: 'Force small' },
  { value: 'medium', label: 'Medium', accessible: 'Force medium' },
  { value: 'large', label: 'Large', accessible: 'Force large' },
  { value: 'compare', label: 'Compare all', accessible: 'Compare all' },
]
const suggestions = [
  { category: 'EXPLAIN', text: 'Explain how DNS works in a few sentences.', icon: MessageSquare },
  { category: 'CODE', text: 'Write a Python function to remove duplicates from a list.', icon: Braces },
  { category: 'REASON', text: 'Compare a cache and a database index.', icon: GitBranch },
]

interface Props { tiers: Tier[]; tierError: boolean; visible: boolean }

export default function Playground({ tiers, tierError, visible }: Props) {
  const local = useAuth().config.mode === 'local'
  const [mode, setMode] = useState<PlaygroundMode>('auto')
  const [draft, setDraft] = useState('')
  const [turns, setTurns] = useState<PlaygroundTurn[]>([])
  const [history, setHistory] = useState<ChatMessage[]>([])
  const [busy, setBusy] = useState(false)
  const [choice, setChoice] = useState<string | null>(null)
  const active = useRef(false)
  const generation = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const thread = useRef<HTMLDivElement>(null)

  useEffect(() => () => controller.current?.abort(), [])
  useEffect(() => {
    if (visible) thread.current?.scrollTo({ top: thread.current.scrollHeight, behavior: 'smooth' })
  }, [turns, visible])

  function updateAnswer(turnId: string, answerMode: RunMode, update: Partial<PlaygroundAnswer>) {
    setTurns((current) => current.map((turn) => turn.id !== turnId ? turn : {
      ...turn, answers: turn.answers.map((answer) => answer.mode === answerMode ? { ...answer, ...update } : answer),
    }))
  }

  async function submitPrompt(promptOverride?: string, modeOverride?: PlaygroundMode) {
    const prompt = (promptOverride ?? draft).trim()
    if (!prompt || active.current || choice) return
    const selectedMode = modeOverride ?? mode
    const compare = selectedMode === 'compare'
    const requestedModes: RunMode[] = compare ? ['small', 'medium', 'large'] : [selectedMode]
    const turnId = crypto.randomUUID()
    const version = ++generation.current
    const requestController = new AbortController()
    const messages: ChatMessage[] = [...history, { role: 'user', content: prompt }]
    controller.current = requestController
    active.current = true
    setBusy(true)
    setDraft('')
    setChoice(compare ? turnId : null)
    setTurns((current) => [...current, {
      id: turnId, prompt, mode: selectedMode, messages,
      answers: requestedModes.map((requestedMode) => ({ mode: requestedMode, state: 'queued' })),
    }])
    let successful = false
    let singleResponse: ChatCompletion | null = null
    try {
      for (const requestedMode of requestedModes) {
        if (requestController.signal.aborted || generation.current !== version) break
        updateAnswer(turnId, requestedMode, { state: 'loading' })
        try {
          const response = await api.chat(messages, requestedMode, requestController.signal)
          if (requestController.signal.aborted || generation.current !== version) break
          if (!response.choices[0]?.message.content.trim()) throw new Error('The model returned no text.')
          successful = true
          singleResponse = response
          updateAnswer(turnId, requestedMode, { state: 'done', response })
        } catch (error) {
          if (requestController.signal.aborted) break
          updateAnswer(turnId, requestedMode, { state: 'error', error: error instanceof Error ? error.message : 'The request failed.' })
        }
      }
    } finally {
      if (generation.current === version) {
        setTurns((current) => current.map((turn) => turn.id !== turnId ? turn : {
          ...turn, answers: turn.answers.map((answer) => answer.state === 'queued' || answer.state === 'loading' ? { ...answer, state: 'cancelled' } : answer),
        }))
        if (compare) setChoice(successful ? turnId : null)
        else if (singleResponse) setHistory([...messages, { role: 'assistant', content: singleResponse.choices[0].message.content }])
        active.current = false
        controller.current = null
        setBusy(false)
        if (!compare || !successful) window.requestAnimationFrame(() => input.current?.focus())
      }
    }
  }

  function chooseAnswer(turn: PlaygroundTurn, answerMode: RunMode) {
    if (busy || choice !== turn.id) return
    const response = turn.answers.find((answer) => answer.mode === answerMode)?.response
    if (!response) return
    setHistory([...turn.messages, { role: 'assistant', content: response.choices[0].message.content }])
    setTurns((current) => current.map((item) => item.id === turn.id ? { ...item, selectedMode: answerMode } : item))
    setChoice(null)
    window.requestAnimationFrame(() => input.current?.focus())
  }

  function clearChat() {
    generation.current += 1
    controller.current?.abort()
    controller.current = null
    active.current = false
    setBusy(false)
    setTurns([])
    setHistory([])
    setChoice(null)
    setDraft('')
    window.requestAnimationFrame(() => input.current?.focus())
  }

  return <div className={styles.workspace}>
    <div className={styles.toolbar}>
      <div className={styles.modeGroup}>
        <span className={styles.toolbarLabel}>ROUTING</span>
        <fieldset className={styles.modes} aria-label="Routing mode">
          {modes.map((item) => <label key={item.value} className={`${styles.mode} ${mode === item.value ? styles.activeMode : ''}`}>
            <input type="radio" name="routing-mode" value={item.value} aria-label={item.accessible} checked={mode === item.value} disabled={busy || choice !== null} onChange={() => setMode(item.value)} />
            {item.value === 'auto' && <GitBranch size={13} />}{item.value === 'compare' && <Layers3 size={13} />}<span>{item.label}</span>
          </label>)}
        </fieldset>
      </div>
      <button type="button" className={styles.clear} onClick={clearChat} disabled={!turns.length && !draft} aria-label="Clear chat" title="Clear this conversation"><Trash2 size={14} /><span>Clear chat</span></button>
    </div>
    <div className={styles.models} aria-label="Configured model tiers">
      {tiers.length ? tiers.map((tier) => <div key={tier.name} className={styles.modelItem} title={!tier.enabled ? (local ? 'Disabled; resolves to medium' : 'Disabled workspace tier') : tier.reachable ? 'Model available' : 'Model unavailable'}>
        <TierBadge tier={tier.name} /><span className={!tier.enabled || !tier.reachable ? styles.unavailable : ''}>{tier.enabled ? tier.model : local ? 'Medium fallback' : 'Disabled'}</span>
        {tier.enabled && !tier.reachable && <span className={styles.warningDot} />}
      </div>) : <span className={styles.modelLoading}>{tierError ? 'Tier status unavailable' : local ? 'Checking model availability' : 'No workspace tiers loaded'}</span>}
    </div>

    <div className={styles.thread} ref={thread} aria-label="Conversation">
      {!turns.length ? <div className={styles.empty}>
        <div className={styles.emptyMark}><Route size={31} strokeWidth={1.4} /></div>
        <h2>New conversation</h2>
        <div className={styles.suggestions}>
          {suggestions.map(({ category, text, icon: Icon }) => <button key={category} type="button" className={styles.suggestion} onClick={() => { setDraft(text); input.current?.focus() }}>
            <span className={styles.suggestionHeading}><Icon size={15} /><span>{category}</span><ArrowUpRight size={14} /></span>
            <span className={styles.suggestionText}>{text}</span>
          </button>)}
        </div>
      </div> : <div className={styles.turns}>
        {turns.map((turn, index) => <article key={turn.id} className={`${styles.turn} ${turn.mode === 'compare' ? styles.compareTurn : ''}`}>
          <div className={styles.userMessage}><span className={styles.userLabel}>YOU<span>{String(index + 1).padStart(2, '0')}</span></span><p>{turn.prompt}</p></div>
          {turn.mode === 'compare' && <div className={styles.compareHeading}><Layers3 size={14} /><span>Compare all</span><span className={styles.compareStatus}>{turn.selectedMode ? 'Response selected' : busy && index === turns.length - 1 ? 'In progress' : choice === turn.id ? 'Selection pending' : 'Finished'}</span></div>}
          <div className={turn.mode === 'compare' ? styles.compareAnswers : styles.singleAnswer}>
            {turn.answers.map((answer) => <AnswerCard key={answer.mode} answer={answer} compare={turn.mode === 'compare'} canSelect={!busy && choice === turn.id && Boolean(answer.response)} selected={turn.selectedMode === answer.mode} onSelect={(answerMode) => chooseAnswer(turn, answerMode)} />)}
          </div>
          {index === turns.length - 1 && !busy && !choice && turn.answers.every((answer) => !answer.response) && <button type="button" className={styles.retry} onClick={() => void submitPrompt(turn.prompt, turn.mode)}><RotateCcw size={13} />Retry prompt</button>}
        </article>)}
      </div>}
    </div>

    <div className={styles.composeArea}>
      <form className={styles.composer} onSubmit={(event) => { event.preventDefault(); void submitPrompt() }}>
        <textarea ref={input} aria-label="Message" placeholder={choice && !busy ? 'Response selection pending' : 'Message SmartRoute...'} value={draft} onChange={(event) => setDraft(event.target.value)} disabled={busy || choice !== null} rows={2} onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submitPrompt() }
        }} />
        <div className={styles.composeControls}>
          <span className={styles.context}><Layers3 size={13} />{history.length ? `${history.length} messages in context` : 'New session'}</span>
          {busy ? <button type="button" className={styles.send} onClick={() => controller.current?.abort()} aria-label="Stop waiting" title="Stop waiting"><Square size={14} fill="currentColor" /></button> : <button type="submit" className={styles.send} disabled={!draft.trim() || choice !== null} aria-label="Send message" title="Send message"><ArrowUp size={19} /></button>}
        </div>
      </form>
      <div className={styles.composeFooter}><span><GitBranch size={12} />{modes.find((item) => item.value === mode)?.accessible}</span><span>{busy ? 'Request in progress' : choice ? 'Response selection pending' : `${turns.length} ${turns.length === 1 ? 'turn' : 'turns'}`}</span></div>
    </div>
  </div>
}