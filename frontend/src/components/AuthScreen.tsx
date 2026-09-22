// Delegate password and email recovery flows to Neon without storing credentials in the app.
import { useEffect, useState } from 'react'
import { ArrowRight, LoaderCircle, Route } from 'lucide-react'
import type { ManagedAuthClient } from '../auth'
import styles from './AuthScreen.module.css'

interface Props { client: ManagedAuthClient; onSignedIn: () => Promise<void>; connectionError: string }

export default function AuthScreen({ client, onSignedIn, connectionError }: Props) {
  const resetToken = new URLSearchParams(location.search).get('token')
  const [mode, setMode] = useState<'login' | 'signup' | 'recover' | 'reset'>(location.pathname.replace(/\/+$/, '') === '/reset-password' && resetToken ? 'reset' : 'login')
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')

  useEffect(() => { document.title = `SmartRoute | ${mode === 'login' ? 'Sign in' : mode === 'signup' ? 'Create account' : 'Account recovery'}` }, [mode])

  function changeMode(next: typeof mode) { setMode(next); setPassword(''); setError(''); setNotice('') }

  async function submit() {
    if (busy) return
    setBusy(true)
    setError('')
    setNotice('')
    try {
      if (mode === 'recover') {
        const result = await client.requestPasswordReset({ email, redirectTo: `${location.origin}/reset-password` })
        if (result.error) throw new Error(result.error.message || 'Recovery could not be requested.')
        setNotice('If the account exists, a recovery email has been requested.')
      } else if (mode === 'reset') {
        const result = await client.resetPassword({ newPassword: password, token: resetToken ?? '' })
        if (result.error) throw new Error(result.error.message || 'Password reset failed.')
        setPassword('')
        history.replaceState(null, '', '/')
        setMode('login')
        setNotice('Password updated. Sign in to continue.')
      } else {
        const result = mode === 'signup'
          ? await client.signUp.email({ email, password, name, callbackURL: location.origin })
          : await client.signIn.email({ email, password })
        if (result.error) throw new Error(result.error.message || 'Sign-in failed.')
        setPassword('')
        await onSignedIn()
        if (mode === 'signup') setNotice('Account created. Check your email if verification is required.')
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Authentication failed.') }
    finally { setBusy(false) }
  }

  return <main className={styles.page}>
    <div className={styles.brand}><span><Route size={25} /></span>SmartRoute.</div>
    <section className={styles.panel}>
      <span className={styles.eyebrow}>PRIVATE WORKSPACE</span>
      <h1>{mode === 'signup' ? 'Create your account' : mode === 'recover' ? 'Recover your account' : mode === 'reset' ? 'Set a new password' : 'Welcome back'}</h1>
      <form onSubmit={(event) => { event.preventDefault(); void submit() }}>
        {mode === 'signup' && <label>Name<input value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" required maxLength={160} disabled={busy} /></label>}
        {mode !== 'reset' && <label>Email<input type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" required disabled={busy} /></label>}
        {mode !== 'recover' && <label>Password<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete={mode === 'login' ? 'current-password' : 'new-password'} minLength={8} required disabled={busy} /></label>}
        {(error || connectionError) && <p className={styles.error} role="alert">{error || connectionError}</p>}
        {notice && <p className={styles.notice} role="status">{notice}</p>}
        <button className={styles.submit} type="submit" disabled={busy}>{busy ? <LoaderCircle size={16} className={styles.spinner} /> : <ArrowRight size={16} />}{mode === 'signup' ? 'Create account' : mode === 'recover' ? 'Send recovery email' : mode === 'reset' ? 'Update password' : 'Sign in'}</button>
      </form>
      <div className={styles.links}>
        <button type="button" disabled={busy} onClick={() => changeMode(mode === 'login' ? 'signup' : 'login')}>{mode === 'login' ? 'Create an account' : 'Back to sign in'}</button>
        {mode === 'login' && <button type="button" disabled={busy} onClick={() => changeMode('recover')}>Forgot password?</button>}
      </div>
      <span className={styles.preview}>Managed authentication</span>
    </section>
  </main>
}