// Present the public product entry with real interface captures and clearly labeled demo data.
import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { ArrowDown, ArrowRight, ArrowUpRight, Check, ChevronRight, Code2, Copy, GitBranch, KeyRound, ListFilter, Route, ShieldCheck, X } from 'lucide-react'
import { Link } from 'react-router-dom'
import styles from './Landing.module.css'

const previews = [
  { id: 'dashboard', label: 'Dashboard', title: 'See the whole picture.', detail: 'Routing distribution, feedback and estimated costs in one workspace.', image: '/screenshots/dashboard.png?v=2', alt: 'SmartRoute dashboard with illustrative tier distribution, cost and feedback charts' },
  { id: 'playground', label: 'Playground', title: 'Follow the decision.', detail: 'A prompt, a selected model and the routing details behind its answer.', image: '/screenshots/playground.png?v=2', alt: 'SmartRoute Playground showing a sample summary and its model, confidence, latency and estimated cost' },
  { id: 'requests', label: 'Request history', title: 'Keep the trail.', detail: 'Inspect conversations, provider attempts, feedback and recorded usage.', image: '/screenshots/requests.png?v=2', alt: 'SmartRoute request history with synthetic prompts, tiers, sources and estimated costs' },
]
const example = `from smartroute_client import SmartRoute\n\nwith SmartRoute() as client:\n    result = client.chat("Summarize this update")\n    print(result.content)\n    print(result.tier, result.cost_usd)`

export default function Landing() {
  const [previewIndex, setPreviewIndex] = useState(0)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState('')
  const [expanded, setExpanded] = useState(false)
  const lightbox = useRef<HTMLDialogElement>(null)
  const preview = previews[previewIndex]
  const install = 'python -m pip install smartroute-client==0.1.0'

  useEffect(() => { document.title = 'SmartRoute | Adaptive LLM routing' }, [])
  useEffect(() => {
    const dialog = lightbox.current
    if (!expanded || !dialog) return
    dialog.showModal()
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const close = (event: globalThis.KeyboardEvent) => { if (event.key === 'Escape') { event.preventDefault(); setExpanded(false) } }
    document.addEventListener('keydown', close, true)
    return () => { document.removeEventListener('keydown', close, true); dialog.close(); document.body.style.overflow = overflow }
  }, [expanded])

  function changeTab(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === 'ArrowRight' ? (index + 1) % previews.length : event.key === 'ArrowLeft' ? (index + previews.length - 1) % previews.length : event.key === 'Home' ? 0 : event.key === 'End' ? previews.length - 1 : null
    if (next === null) return
    event.preventDefault()
    setPreviewIndex(next)
    document.getElementById(`preview-tab-${previews[next].id}`)?.focus()
  }

  async function copyInstall() {
    try { await navigator.clipboard.writeText(install); setCopied(true); setCopyError('') }
    catch { setCopyError('Clipboard unavailable.'); setCopied(false) }
  }

  return <div className={styles.landing} id="top">
    <a href="#public-content" className={styles.skip}>Skip to content</a>
    <header className={styles.header}><a href="#top" className={styles.brand} aria-label="SmartRoute home"><span className={styles.brandMark}><Route size={21} /></span>SmartRoute<span className={styles.brandDot}>.</span></a>
      <nav className={styles.nav} aria-label="Product navigation"><a href="#platform">Platform</a><a href="#workspace-preview">Screenshots</a><a href="#developers">Developers</a></nav>
      <div className={styles.headerActions}><Link to="/sign-in" className={styles.signIn}>Sign in<ArrowUpRight size={14} /></Link><Link to="/sign-up" className={`${styles.primary} ${styles.headerCreate}`}>Create workspace<ArrowRight size={15} /></Link></div>
    </header>
    <main id="public-content">
      <section className={styles.hero} aria-labelledby="landing-title">
        <div className={styles.heroCopy}><p className={styles.eyebrow}><span />OPEN-SOURCE MODEL ROUTING</p><h1 id="landing-title">SmartRoute<span>.</span></h1><p className={styles.heroStatement}>Your models. One clear view.</p><p className={styles.heroDescription}>Route requests across your models and trace every answer, confidence check and estimated cost.</p>
          <div className={styles.heroActions}><Link to="/sign-up" className={styles.primary}>Get started<ArrowRight size={17} /></Link><a href="#workspace-preview" className={styles.secondary}>See workspace<ArrowDown size={16} /></a></div>
          <p className={styles.heroNote}>OpenAI + Anthropic<span />Your provider keys<span />Your private workspace</p>
        </div>
      </section>
      <div className={styles.compatibility}><span>Built around your stack</span><strong>OpenAI-compatible API</strong><strong>Native Anthropic</strong><a href="https://pypi.org/project/smartroute-client/0.1.0/" target="_blank" rel="noreferrer">Python SDK<ArrowUpRight size={14} /></a><a href="https://github.com/umarsayed12/SmartRoute" target="_blank" rel="noreferrer">Open source<Code2 size={15} /></a></div>

      <section className={styles.section} id="platform" aria-labelledby="platform-title"><div className={styles.sectionIntro}><p className={styles.eyebrow}>A ROUTING LAYER YOU CAN INSPECT</p><h2 id="platform-title">Less guesswork.<br />More context.</h2><p>Choose your models, keep the routing policy in your workspace, and see what happened after each request.</p></div>
        <div className={styles.capabilities}>
          <article><span className={styles.featureNumber}>01 / ROUTE</span><GitBranch className={styles.mint} size={27} /><h3>Start with a tier.<br />Escalate with a reason.</h3><p>Use explainable rules or a feedback-trained router. Confidence checks can move an answer to the next enabled tier.</p></article>
          <article><span className={styles.featureNumber}>02 / INSPECT</span><ListFilter className={styles.amber} size={27} /><h3>The answer is only<br />part of the story.</h3><p>Review model choices, latency, reported tokens and every recorded answer or self-check attempt.</p></article>
          <article><span className={styles.featureNumber}>03 / OWN</span><ShieldCheck className={styles.rose} size={27} /><h3>Your workspace.<br />Your model access.</h3><p>Bring supported provider credentials, configure your tiers, and connect applications with revocable gateway keys.</p></article>
        </div>
      </section>

      <section className={`${styles.section} ${styles.previewSection}`} id="workspace-preview" aria-labelledby="preview-title"><div className={styles.previewHeading}><div><p className={styles.eyebrow}>INSIDE SMARTROUTE</p><h2 id="preview-title">{preview.title}</h2><p>{preview.detail}</p></div><div className={styles.tabs} role="tablist" aria-label="Product screenshots">{previews.map((item, index) => <button key={item.id} id={`preview-tab-${item.id}`} type="button" role="tab" aria-selected={previewIndex === index} aria-controls="product-preview-panel" tabIndex={previewIndex === index ? 0 : -1} onClick={() => setPreviewIndex(index)} onKeyDown={(event) => changeTab(event, index)}>{item.label}</button>)}</div></div>
        <div id="product-preview-panel" role="tabpanel" aria-labelledby={`preview-tab-${preview.id}`} tabIndex={0}><figure className={styles.previewFigure}><button type="button" className={styles.imageButton} aria-label={`Enlarge ${preview.label} screenshot`} onClick={() => setExpanded(true)}><img src={preview.image} alt={preview.alt} width={1440} height={1600} loading="lazy" /></button><figcaption><span>DEMO WORKSPACE</span>Real interface. Illustrative sample data, not production benchmarks.</figcaption></figure></div>
      </section>

      <section className={styles.developers} id="developers" aria-labelledby="developers-title"><div className={styles.developerInner}><div className={styles.developerCopy}><p className={styles.eyebrow}><Code2 size={16} /> FOR DEVELOPERS</p><h2 id="developers-title">One client.<br />A visible request trail.</h2><p>Connect your application to the same gateway as the web workspace. The Python SDK returns the answer and its routing metadata together.</p><a href="https://github.com/umarsayed12/SmartRoute/tree/main/sdk" target="_blank" rel="noreferrer" className={styles.textLink}>Read the SDK reference<ArrowUpRight size={16} /></a><div className={styles.install}><code>{install}</code><button type="button" title="Copy installation command" aria-label="Copy installation command" onClick={() => void copyInstall()}>{copied ? <Check size={17} /> : <Copy size={17} />}</button></div>{copied && <span className={styles.copyStatus} role="status">Installation command copied</span>}{copyError && <span className={styles.copyStatus} role="alert">{copyError}</span>}</div><div className={styles.codePanel}><div className={styles.codeTitle}><span>application.py</span><span>Python 3.11+</span></div><pre><code>{example}</code></pre><p><KeyRound size={14} />Environment: SMARTROUTE_BASE_URL + SMARTROUTE_API_KEY</p></div></div></section>

      <section className={`${styles.section} ${styles.startSection}`} aria-labelledby="start-title"><div><p className={styles.eyebrow}>FROM SETUP TO FIRST REQUEST</p><h2 id="start-title">Bring the models.<br />Keep the visibility.</h2></div><ol className={styles.steps}><li><span>01</span><div><h3>Create a private workspace</h3><p>Sign in and verify your email.</p></div></li><li><span>02</span><div><h3>Connect your providers</h3><p>Add credentials, model tiers and explicit token prices.</p></div></li><li><span>03</span><div><h3>Make a request</h3><p>Use Playground or an application gateway key.</p></div></li></ol><Link to="/sign-up" className={styles.primary}>Create workspace<ArrowRight size={17} /></Link></section>

      <section className={`${styles.section} ${styles.faq}`} aria-labelledby="faq-title"><h2 id="faq-title">Before you connect.</h2><div>
        <details><summary>Does SmartRoute provide the models?<ChevronRight size={18} /></summary><p>No. You bring access to supported OpenAI or Anthropic models and pay your provider. SmartRoute supplies the routing gateway and workspace.</p></details>
        <details><summary>Are the costs exact provider invoices?<ChevronRight size={18} /></summary><p>No. Costs use the rates you configure and include reported answer and self-check usage. Cache-specific pricing can differ, and failed calls may have unknown cost.</p></details>
        <details><summary>Does confidence guarantee a correct answer?<ChevronRight size={18} /></summary><p>No. It is a routing signal, not a correctness guarantee. The highest enabled tier uses a stopping convention; evaluate the models on your own workload.</p></details>
        <details><summary>Where do my prompts and keys go?<ChevronRight size={18} /></summary><p>The gateway processes and stores requests in your workspace and sends model requests to your configured provider. Provider keys are encrypted at rest; gateway keys are shown once and can be revoked. Hosted request retention is shown in Settings.</p></details>
      </div></section>
    </main>
    <footer className={styles.footer}><a href="#top" className={styles.brand}><Route size={20} />SmartRoute.</a><p>Open-source gateway. Provider charges apply.</p><div><a href="https://github.com/umarsayed12/SmartRoute" target="_blank" rel="noreferrer">GitHub<ArrowUpRight size={14} /></a><a href="https://pypi.org/project/smartroute-client/0.1.0/" target="_blank" rel="noreferrer">PyPI<ArrowUpRight size={14} /></a><Link to="/sign-in">Sign in<ArrowRight size={14} /></Link></div></footer>
    <dialog ref={lightbox} className={styles.lightbox} aria-labelledby="screenshot-title" onCancel={(event) => { event.preventDefault(); setExpanded(false) }} onClose={() => setExpanded(false)} onClick={(event) => { if (event.target === event.currentTarget) { const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) setExpanded(false) } }}><div><h2 id="screenshot-title">{preview.label} <span>Sample data</span></h2><button type="button" title="Close screenshot" aria-label="Close screenshot" onClick={() => setExpanded(false)}><X size={21} /></button></div><img src={preview.image} alt={preview.alt} width={1440} height={1600} /></dialog>
  </div>
}