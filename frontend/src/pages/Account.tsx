// Manage the owner's gateway keys while keeping one-time secrets only in component memory.
import { useEffect, useRef, useState } from 'react'
import { Check, Copy, KeyRound, LoaderCircle, Mail, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import type { GatewayKey } from '../types'
import DataTable from '../components/DataTable'
import type { Column } from '../components/DataTable'
import ui from './Workspace.module.css'
import styles from './Account.module.css'

export default function Account() {
  const auth = useAuth()
  const [keys, setKeys] = useState<GatewayKey[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [verificationCode, setVerificationCode] = useState('')
  const [name, setName] = useState('Application')
  const [days, setDays] = useState(90)
  const [secret, setSecret] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [revision, setRevision] = useState(0)
  const operation = useRef<AbortController | null>(null)

  useEffect(() => () => operation.current?.abort(), [])
  useEffect(() => {
    const controller = new AbortController()
    api.keys(controller.signal).then((result) => { if (!controller.signal.aborted) setKeys(result) }).catch((failure: unknown) => {
      if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Keys could not be loaded.')
    }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [revision])

  async function perform(action: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return
    const controller = new AbortController()
    operation.current = controller
    setBusy(true)
    setError('')
    setNotice('')
    try { await action(controller.signal) }
    catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Operation failed.') }
    finally { operation.current = null; if (!controller.signal.aborted) setBusy(false) }
  }

  const columns: Column<GatewayKey>[] = [
    { id: 'name', label: 'Name', render: (key) => key.name },
    { id: 'prefix', label: 'Prefix', render: (key) => <span className={ui.mono}>{key.key_prefix}...</span> },
    { id: 'created', label: 'Created', render: (key) => new Date(key.created_at).toLocaleDateString() },
    { id: 'expires', label: 'Expires', render: (key) => key.expires_at ? new Date(key.expires_at).toLocaleDateString() : 'No expiration' },
    { id: 'used', label: 'Last used', render: (key) => key.last_used_at ? new Date(key.last_used_at).toLocaleString() : 'Never' },
    { id: 'status', label: 'Status', render: (key) => key.revoked_at ? 'Revoked' : key.expires_at && new Date(key.expires_at).getTime() <= Date.now() ? 'Expired' : 'Active' },
    { id: 'action', label: 'Action', render: (key) => key.revoked_at ? null : confirm === key.id ? <div className={ui.actions}><button type="button" className={ui.button} disabled={busy} onClick={() => void perform(async (signal) => { await api.revokeKey(key.id, signal); if (!signal.aborted) { setConfirm(null); setRevision((value) => value + 1) } })}>Confirm revoke</button><button type="button" className={ui.iconButton} disabled={busy} title="Cancel revocation" aria-label="Cancel revocation" onClick={() => setConfirm(null)}><X size={14} /></button></div> : <button type="button" className={ui.iconButton} disabled={busy} title="Revoke key" aria-label={`Revoke ${key.name}`} onClick={() => setConfirm(key.id)}><Trash2 size={14} /></button> },
  ]

  return <div className={ui.page}>
    <div className={ui.toolbar}><div className={styles.identity}><h2>{auth.account?.workspace.name}</h2><p className={ui.muted}>{auth.account?.user?.email}</p></div><span className={styles.plan}>{auth.account?.workspace.plan} plan</span></div>
    {error && <div className={ui.error} role="alert">{error}</div>}{notice && <p className={ui.success} role="status">{notice}</p>}
    {!auth.account?.user?.email_verified && <section className={styles.verification} aria-label="Email verification">
      <span>Email verification required for API keys</span>
      <form className={styles.verificationForm} onSubmit={(event) => { event.preventDefault(); void perform(async (signal) => { await auth.verifyEmailCode(verificationCode); if (!signal.aborted) { setVerificationCode(''); setNotice('Email verified.') } }) }}>
        <label className={ui.field}>Verification code<input autoComplete="one-time-code" inputMode="numeric" value={verificationCode} onChange={(event) => setVerificationCode(event.target.value)} maxLength={12} required disabled={busy} /></label>
        <button type="submit" className={ui.primary} disabled={busy || !verificationCode.trim()}><Check size={14} />Verify code</button>
      </form>
      <div className={ui.actions}><button type="button" className={ui.button} disabled={busy} onClick={() => void perform(async (signal) => { await auth.sendVerification(); if (!signal.aborted) setNotice('Verification code requested.') })}><Mail size={14} />Send new code</button><button type="button" className={ui.button} disabled={busy} onClick={() => void perform(async () => { await auth.refreshAccount() })}><RefreshCw size={14} />Refresh verification</button></div>
    </section>}
    <section className={ui.section}><h2 className={ui.sectionTitle}>Create gateway key</h2><form className={styles.form} onSubmit={(event) => { event.preventDefault(); void perform(async (signal) => { const result = await api.createKey(name.trim(), days, signal); if (!signal.aborted) { setSecret(result.key); setCopied(false); setRevision((value) => value + 1) } }) }}>
      <label className={ui.field}>Key name<input value={name} onChange={(event) => setName(event.target.value)} required maxLength={80} disabled={busy} /></label>
      <label className={ui.field}>Expiration<select value={days} onChange={(event) => setDays(Number(event.target.value))} disabled={busy}>{[7, 30, 90, 365].map((value) => <option key={value} value={value}>{value} days</option>)}</select></label>
      <button type="submit" className={ui.primary} disabled={busy || !name.trim() || !auth.account?.user?.email_verified || secret !== null}>{busy ? <LoaderCircle className={ui.spinner} size={15} /> : <Plus size={15} />}Create key</button>
    </form></section>
    {secret && <section className={styles.secret} aria-label="New gateway key"><div className={ui.row}><KeyRound size={16} /><strong>One-time API key</strong></div><div className={styles.secretControls}><input type="password" value={secret} readOnly aria-label="New API key" autoComplete="off" /><button type="button" className={ui.iconButton} title={copied ? 'Copied' : 'Copy API key'} aria-label={copied ? 'API key copied' : 'Copy API key'} onClick={() => void navigator.clipboard.writeText(secret).then(() => setCopied(true)).catch(() => setError('The key could not be copied.'))}>{copied ? <Check size={16} /> : <Copy size={16} />}</button><button type="button" className={ui.iconButton} title="Dismiss secret" aria-label="Dismiss secret" onClick={() => setSecret(null)}><X size={16} /></button></div></section>}
    <section className={ui.section}><div className={ui.toolbar}><h2>API keys</h2><button type="button" className={ui.iconButton} aria-label="Refresh API keys" title="Refresh API keys" disabled={loading} onClick={() => { setLoading(true); setError(''); setRevision((value) => value + 1) }}><RefreshCw size={15} /></button></div>{loading && !keys.length ? <div className={ui.loading}>Loading keys</div> : <DataTable rows={keys} columns={columns} rowKey={(key) => key.id} label="Workspace API keys" emptyText="No gateway keys" />}</section>
    <section className={ui.section}><h2 className={ui.sectionTitle}>SDK</h2><span className={ui.muted}>Not published yet</span></section>
  </div>
}