// Manage encrypted workspace credentials and explicit owned-model routing tiers.
import { useEffect, useRef, useState } from 'react'
import { Check, KeyRound, LoaderCircle, Pencil, Plus, RefreshCw, Save, Trash2, X } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { formatCost } from '../format'
import type { ConfiguredModel, ProviderCredential, TierName } from '../types'
import TierBadge from '../components/TierBadge'
import DataTable from '../components/DataTable'
import type { Column } from '../components/DataTable'
import ui from './Workspace.module.css'
import styles from './Models.module.css'

export default function Models({ onChanged }: { onChanged: () => void }) {
  const auth = useAuth()
  const [credentials, setCredentials] = useState<ProviderCredential[]>([])
  const [models, setModels] = useState<ConfiguredModel[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [revision, setRevision] = useState(0)
  const [busy, setBusy] = useState(false)
  const [provider, setProvider] = useState<ProviderCredential['provider']>('openai')
  const [label, setLabel] = useState('Primary')
  const [secret, setSecret] = useState('')
  const [rotating, setRotating] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [confirmTierDelete, setConfirmTierDelete] = useState<TierName | null>(null)
  const [tier, setTier] = useState<TierName>('small')
  const [credentialId, setCredentialId] = useState('')
  const [modelId, setModelId] = useState('')
  const [inputPrice, setInputPrice] = useState('')
  const [outputPrice, setOutputPrice] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [temperature, setTemperature] = useState(true)
  const [checkTokens, setCheckTokens] = useState('256')
  const operation = useRef<AbortController | null>(null)
  const verified = auth.account?.user?.email_verified === true
  const validModel = Boolean(modelId.trim() && credentialId && inputPrice.trim() && outputPrice.trim() && [Number(inputPrice), Number(outputPrice)].every((value) => Number.isFinite(value) && value >= 0) && Number.isInteger(Number(checkTokens)) && Number(checkTokens) >= 32 && Number(checkTokens) <= 1024)

  useEffect(() => () => operation.current?.abort(), [])
  useEffect(() => {
    const controller = new AbortController()
    Promise.all([api.credentials(controller.signal), api.models(controller.signal)]).then(([savedCredentials, savedModels]) => {
      if (controller.signal.aborted) return
      setCredentials(savedCredentials)
      setModels(savedModels)
      setCredentialId((current) => savedCredentials.some((item) => item.id === current) ? current : savedCredentials[0]?.id ?? '')
    }).catch((failure: unknown) => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Model configuration could not be loaded.') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [revision])

  async function perform(action: (signal: AbortSignal) => Promise<void>) {
    if (operation.current) return
    const controller = new AbortController()
    operation.current = controller
    setBusy(true); setError(''); setNotice('')
    try { await action(controller.signal); if (!controller.signal.aborted) { setRevision((value) => value + 1); onChanged() } }
    catch (failure) { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : 'Configuration could not be saved.') }
    finally { operation.current = null; if (!controller.signal.aborted) setBusy(false) }
  }

  function editTier(value: TierName) {
    setTier(value)
    const existing = models.find((item) => item.tier === value)
    setCredentialId(existing?.credential_id ?? credentials[0]?.id ?? '')
    setModelId(existing?.model ?? '')
    setInputPrice(existing ? String(existing.input_price_per_1k) : '')
    setOutputPrice(existing ? String(existing.output_price_per_1k) : '')
    setEnabled(existing?.enabled ?? true)
    setTemperature(existing?.send_temperature ?? true)
    setCheckTokens(String(existing?.self_check_max_tokens ?? 256))
  }

  const credentialColumns: Column<ProviderCredential>[] = [
    { id: 'label', label: 'Credential', render: (item) => item.label },
    { id: 'provider', label: 'Provider', render: (item) => item.provider === 'openai' ? 'OpenAI' : 'Anthropic' },
    { id: 'suffix', label: 'Key suffix', render: (item) => <span className={ui.mono}>...{item.key_suffix}</span> },
    { id: 'actions', label: 'Actions', render: (item) => <div className={ui.actions}><button type="button" className={ui.iconButton} title="Replace provider key" aria-label={`Replace ${item.label} key`} disabled={busy || !verified} onClick={() => { setRotating(item.id); setProvider(item.provider); setLabel(item.label); setSecret('') }}><Pencil size={14} /></button>{confirmDelete === item.id ? <><button type="button" className={ui.button} disabled={busy} onClick={() => void perform(async (signal) => { await api.deleteCredential(item.id, signal); if (!signal.aborted) { setConfirmDelete(null); setNotice('Credential and linked models removed.') } })}>Delete credential and models</button><button type="button" className={ui.iconButton} title="Cancel deletion" aria-label="Cancel deletion" onClick={() => setConfirmDelete(null)}><X size={14} /></button></> : <button type="button" className={ui.iconButton} title="Delete credential" aria-label={`Delete ${item.label} credential`} disabled={busy} onClick={() => setConfirmDelete(item.id)}><Trash2 size={14} /></button>}</div> },
  ]
  const modelColumns: Column<ConfiguredModel>[] = [
    { id: 'tier', label: 'Tier', render: (item) => <TierBadge tier={item.tier} /> },
    { id: 'model', label: 'Model', render: (item) => <span className={ui.mono}>{item.model}</span> },
    { id: 'provider', label: 'Provider', render: (item) => item.provider },
    { id: 'prices', label: 'Input / output per 1k', render: (item) => <span className={ui.mono}>{formatCost(Number(item.input_price_per_1k))} / {formatCost(Number(item.output_price_per_1k))}</span> },
    { id: 'enabled', label: 'Status', render: (item) => item.enabled ? 'Enabled' : 'Disabled' },
    { id: 'edit', label: 'Actions', render: (item) => <div className={ui.actions}><button type="button" className={ui.iconButton} title="Edit tier" aria-label={`Edit ${item.tier} model`} disabled={busy} onClick={() => editTier(item.tier)}><Pencil size={14} /></button>{confirmTierDelete === item.tier ? <><button type="button" className={ui.button} disabled={busy} onClick={() => void perform(async (signal) => { await api.deleteModel(item.tier, signal); if (!signal.aborted) { setConfirmTierDelete(null); if (tier === item.tier) { setModelId(''); setInputPrice(''); setOutputPrice('') } setNotice('Model tier removed.') } })}>Remove tier</button><button type="button" className={ui.iconButton} title="Cancel tier removal" aria-label="Cancel tier removal" onClick={() => setConfirmTierDelete(null)}><X size={14} /></button></> : <button type="button" className={ui.iconButton} title="Remove tier" aria-label={`Remove ${item.tier} model`} disabled={busy} onClick={() => setConfirmTierDelete(item.tier)}><Trash2 size={14} /></button>}</div> },
  ]

  return <div className={ui.page}>
    <div className={ui.toolbar}><h2>Workspace models</h2><button type="button" className={ui.iconButton} title="Refresh model configuration" aria-label="Refresh model configuration" disabled={busy || loading} onClick={() => { setLoading(true); setError(''); setRevision((value) => value + 1) }}><RefreshCw size={15} /></button></div>
    {!verified && <p className={ui.bad}>Email verification required for model configuration</p>}
    {error && <div className={ui.error} role="alert">{error}</div>}{notice && <p className={ui.success} role="status"><Check size={14} />{notice}</p>}
    <section><h2 className={ui.sectionTitle}>Provider credentials</h2><DataTable rows={credentials} columns={credentialColumns} rowKey={(item) => item.id} label="Provider credentials" emptyText={loading ? 'Loading credentials' : 'No provider credentials'} />
      <form className={styles.credentialsForm} onSubmit={(event) => { event.preventDefault(); void perform(async (signal) => { if (rotating) await api.replaceCredential(rotating, secret, signal); else await api.createCredential(provider, label.trim(), secret, signal); if (!signal.aborted) { setSecret(''); setRotating(null); setNotice('Provider credential saved.') } }) }}>
        <label className={ui.field}>Provider<select value={provider} disabled={busy || Boolean(rotating)} onChange={(event) => setProvider(event.target.value as ProviderCredential['provider'])}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></label>
        <label className={ui.field}>Label<input value={label} onChange={(event) => setLabel(event.target.value)} required maxLength={80} disabled={busy || Boolean(rotating)} /></label>
        <label className={ui.field}>Provider API key<input type="password" autoComplete="off" value={secret} onChange={(event) => setSecret(event.target.value)} required minLength={8} maxLength={4096} disabled={busy} /></label>
        <button type="submit" className={ui.primary} disabled={busy || !verified || !label.trim() || secret.length < 8}>{busy ? <LoaderCircle className={ui.spinner} size={14} /> : <KeyRound size={14} />}{rotating ? 'Replace key' : 'Save credential'}</button>
        {rotating && <button type="button" className={ui.button} disabled={busy} onClick={() => { setRotating(null); setSecret('') }}>Cancel replacement</button>}
      </form>
    </section>
    <section className={ui.section}><h2 className={ui.sectionTitle}>Configured tiers</h2><DataTable rows={models} columns={modelColumns} rowKey={(item) => item.id} label="Workspace model tiers" emptyText={loading ? 'Loading models' : 'No models configured'} /></section>
    <section className={ui.section}><h2 className={ui.sectionTitle}>Configure tier</h2><form className={styles.modelForm} onSubmit={(event) => { event.preventDefault(); if (!validModel) return; void perform(async (signal) => { await api.configureModel(tier, { credential_id: credentialId, model: modelId.trim(), input_price_per_1k: Number(inputPrice), output_price_per_1k: Number(outputPrice), enabled, send_temperature: temperature, self_check_max_tokens: Number(checkTokens) }, signal); if (!signal.aborted) setNotice('Model tier saved.') }) }}>
      <label className={ui.field}>Tier<select value={tier} disabled={busy} onChange={(event) => editTier(event.target.value as TierName)}>{['small', 'medium', 'large'].map((value) => <option key={value}>{value}</option>)}</select></label>
      <label className={ui.field}>Credential<select value={credentialId} disabled={busy} required onChange={(event) => setCredentialId(event.target.value)}><option value="">Select credential</option>{credentials.map((item) => <option key={item.id} value={item.id}>{item.label} ({item.provider})</option>)}</select></label>
      <label className={ui.field}>Model ID<input value={modelId} onChange={(event) => setModelId(event.target.value)} required maxLength={200} disabled={busy} placeholder="Provider model ID" /></label>
      <label className={ui.field}>Input USD / 1,000 tokens<input type="number" min={0} step="any" value={inputPrice} onChange={(event) => setInputPrice(event.target.value)} required disabled={busy} /></label>
      <label className={ui.field}>Output USD / 1,000 tokens<input type="number" min={0} step="any" value={outputPrice} onChange={(event) => setOutputPrice(event.target.value)} required disabled={busy} /></label>
      <label className={ui.field}>Self-check token limit<input type="number" min={32} max={1024} step={1} value={checkTokens} onChange={(event) => setCheckTokens(event.target.value)} required disabled={busy} /></label>
      <label className={styles.toggle}><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={busy} />Enabled</label>
      <label className={styles.toggle} title="Disable for models that reject custom temperature."><input type="checkbox" checked={temperature} onChange={(event) => setTemperature(event.target.checked)} disabled={busy} />Send temperature</label>
      <button type="submit" className={ui.primary} disabled={busy || !verified || !validModel}><Save size={14} />Save tier</button>
    </form></section>
    {!loading && !models.some((item) => item.enabled) && <div className={styles.note}><Plus size={14} /><span>At least one enabled model required</span></div>}
  </div>
}