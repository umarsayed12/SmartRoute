// Show workspace readiness and published SDK examples without copying or retaining credentials.
import { useEffect, useState } from 'react'
import { ArrowUpRight, Check, Circle, Copy, RefreshCw } from 'lucide-react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../auth'
import ui from './Workspace.module.css'
import styles from './Integration.module.css'

interface Props { modelsReady: boolean | null; onRefresh: () => void }

export default function Integration({ modelsReady, onRefresh }: Props) {
  const auth = useAuth()
  const [revision, setRevision] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [activeKeys, setActiveKeys] = useState<number | null>(null)
  const [sdkRequests, setSdkRequests] = useState<number | null>(null)
  const [language, setLanguage] = useState<'python' | 'cli'>('python')
  const [shell, setShell] = useState<'powershell' | 'posix'>('powershell')
  const [copied, setCopied] = useState('')
  const [copyError, setCopyError] = useState('')
  const baseUrl = window.location.origin
  const install = `${shell === 'powershell' ? 'python' : 'python3'} -m venv .venv\n${shell === 'powershell' ? '.\\.venv\\Scripts\\python.exe' : '.venv/bin/python'} -m pip install --index-url https://pypi.org/simple smartroute-client==0.1.0`
  const python = `from getpass import getpass\nfrom smartroute_client import SmartRoute\n\nwith SmartRoute(\n    base_url=${JSON.stringify(baseUrl)},\n    api_key=getpass("SmartRoute gateway key: "),\n) as client:\n    result = client.chat("Hello", max_tokens=64)\n    print(result.content)\n    print(result.request_id)`
  const cli = shell === 'powershell'
    ? `$secureKey = Read-Host 'SmartRoute gateway key' -AsSecureString\n$env:SMARTROUTE_API_KEY = [System.Net.NetworkCredential]::new('', $secureKey).Password\n$env:SMARTROUTE_BASE_URL = '${baseUrl}'\n.\\.venv\\Scripts\\smartroute.exe models\n.\\.venv\\Scripts\\smartroute.exe chat "Hello" --max-tokens 64\nRemove-Item Env:SMARTROUTE_API_KEY\nRemove-Variable secureKey`
    : `read -r -s -p 'SmartRoute gateway key: ' SMARTROUTE_API_KEY\nprintf '\\n'\nexport SMARTROUTE_API_KEY\nexport SMARTROUTE_BASE_URL='${baseUrl}'\n.venv/bin/smartroute models\n.venv/bin/smartroute chat "Hello" --max-tokens 64\nunset SMARTROUTE_API_KEY`

  useEffect(() => {
    const controller = new AbortController()
    Promise.all([api.keys(controller.signal), api.requests({ source: 'sdk', limit: 1 }, controller.signal)]).then(([keys, requests]) => {
      if (controller.signal.aborted) return
      setActiveKeys(keys.filter((key) => !key.revoked_at && (!key.expires_at || new Date(key.expires_at).getTime() > Date.now())).length)
      setSdkRequests(requests.total)
      setError('')
    }).catch((failure: unknown) => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Integration status is unavailable.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [revision])

  async function copy(value: string, name: string) {
    try { await navigator.clipboard.writeText(value); setCopied(name); setCopyError('') }
    catch { setCopyError('Clipboard unavailable.'); setCopied('') }
  }

  const steps = [
    { label: 'Email verification', ready: auth.account?.user?.email_verified === true, value: auth.account?.user?.email_verified ? 'Verified' : 'Required', href: '/account' },
    { label: 'Workspace models', ready: modelsReady === true, value: modelsReady === null ? 'Checking' : modelsReady ? 'Configured' : 'Required', href: '/models' },
    { label: 'Gateway API key', ready: !!activeKeys, value: activeKeys === null ? 'Checking' : `${activeKeys} active`, href: '/account' },
    { label: 'SDK requests', ready: !!sdkRequests, value: sdkRequests === null ? 'Checking' : String(sdkRequests), href: '/requests' },
  ]

  return <div className={ui.page}>
    <div className={ui.toolbar}><h2>Workspace integration</h2><button type="button" className={ui.iconButton} title="Refresh integration status" aria-label="Refresh integration status" disabled={loading} onClick={() => { setLoading(true); setActiveKeys(null); setSdkRequests(null); setRevision((value) => value + 1); onRefresh() }}><RefreshCw size={15} /></button></div>
    {error && <div className={ui.error} role="alert">{error}</div>}
    <ol className={styles.steps}>{steps.map((step) => <li key={step.label}><span className={step.ready ? ui.good : ui.muted}>{step.ready ? <Check size={17} /> : <Circle size={17} />}</span><Link to={step.href}>{step.label}<ArrowUpRight size={13} /></Link><span className={ui.muted}>{error && step.value === 'Checking' ? 'Unavailable' : step.value}</span></li>)}</ol>
    <section className={ui.section}><h3 className={ui.sectionTitle}>Gateway URL</h3><div className={styles.endpoint}><code>{baseUrl}</code><button type="button" className={ui.iconButton} title="Copy gateway URL" aria-label="Copy gateway URL" onClick={() => void copy(baseUrl, 'Gateway URL')}><Copy size={14} /></button></div></section>
    <section className={ui.section}>
      <div className={ui.toolbar}><h3 className={ui.sectionTitle}>Install SDK <span className={styles.badge}>PyPI 0.1.0</span></h3><fieldset className={styles.switches} aria-label="Command shell">{(['powershell', 'posix'] as const).map((value) => <label key={value}><input type="radio" name="command-shell" checked={shell === value} onChange={() => { setShell(value); setCopied('') }} />{value === 'powershell' ? 'PowerShell' : 'Bash'}</label>)}</fieldset></div>
      <div className={styles.codeHeading}><span>Python 3.11+</span><button type="button" className={ui.iconButton} title="Copy installation" aria-label="Copy installation" onClick={() => void copy(install, 'Installation')}><Copy size={14} /></button></div><pre className={styles.code}><code>{install}</code></pre>
    </section>
    <section className={ui.section}>
      <div className={ui.toolbar}><fieldset className={styles.switches} aria-label="Example language">{(['python', 'cli'] as const).map((value) => <label key={value}><input type="radio" name="example-language" checked={language === value} onChange={() => { setLanguage(value); setCopied('') }} />{value === 'python' ? 'Python' : 'CLI'}</label>)}</fieldset><span className={ui.muted}>Provider charges apply</span></div>
      <div className={styles.codeHeading}><span>{language === 'python' ? 'example.py' : shell === 'powershell' ? 'PowerShell' : 'Bash'}</span><button type="button" className={ui.iconButton} title="Copy client example" aria-label="Copy client example" onClick={() => void copy(language === 'python' ? python : cli, 'Client example')}><Copy size={14} /></button></div><pre className={styles.code}><code>{language === 'python' ? python : cli}</code></pre>
    </section>
    {copied && <p className={ui.success} role="status"><Check size={14} />{copied} copied</p>}{copyError && <p className={ui.bad} role="alert">{copyError}</p>}
    <div className={`${ui.actions} ${styles.links}`}><a className={ui.button} href="https://pypi.org/project/smartroute-client/0.1.0/" target="_blank" rel="noreferrer">PyPI package<ArrowUpRight size={14} /></a><a className={ui.button} href="https://github.com/umarsayed12/SmartRoute/tree/main/sdk" target="_blank" rel="noreferrer">SDK reference<ArrowUpRight size={14} /></a><Link to="/account" className={ui.button}>Manage gateway keys</Link></div>
  </div>
}