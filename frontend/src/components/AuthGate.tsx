// Gate workspace rendering on managed authentication while preserving local-prototype mode.
import { useEffect, useRef, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { api, setTokenProvider } from '../api'
import { AuthContext, createManagedAuth, managedAccessToken } from '../auth'
import type { ManagedAuthClient } from '../auth'
import type { ClientConfig, WorkspaceAccount } from '../types'
import App from '../App'
import AuthScreen from './AuthScreen'
import styles from '../App.module.css'

export default function AuthGate() {
  const [config, setConfig] = useState<ClientConfig | null>(null)
  const [client, setClient] = useState<ManagedAuthClient | null>(null)
  const [account, setAccount] = useState<WorkspaceAccount | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [revision, setRevision] = useState(0)
  const subject = useRef<string | null>(null)

  function clearSession() { subject.current = null; setTokenProvider(null); setAccount(null) }

  async function connect(auth: ManagedAuthClient) {
    const session = await auth.getSession()
    if (session.error) throw new Error(session.error.message || 'Session could not be loaded.')
    if (!session.data?.session) { clearSession(); return }
    const userId = session.data.user.id
    subject.current = userId
    setTokenProvider(() => managedAccessToken(auth, userId, clearSession))
    setAccount(await api.me())
    setError('')
  }

  useEffect(() => {
    let active = true
    const controller = new AbortController()
    async function initialize() {
      try {
        const settings = await api.clientConfig(controller.signal)
        if (!active) return
        setConfig(settings)
        if (settings.mode === 'local') { setTokenProvider(null); return }
        if (!settings.auth_url) throw new Error('Managed authentication is not configured.')
        const auth = await createManagedAuth(settings.auth_url)
        if (!active) return
        setClient(() => auth)
        const session = await auth.getSession()
        if (!active) return
        if (session.data?.session) {
          const userId = session.data.user.id
          subject.current = userId
          setTokenProvider(() => managedAccessToken(auth, userId, clearSession))
          const profile = await api.me(controller.signal)
          if (active) setAccount(profile)
        }
      } catch (failure) {
        if (active) setError(failure instanceof Error ? failure.message : 'Workspace could not be initialized.')
      } finally { if (active) setLoading(false) }
    }
    void initialize()
    return () => { active = false; controller.abort(); setTokenProvider(null) }
  }, [revision])

  useEffect(() => {
    if (!client) return
    let active = true
    const checkSession = () => {
      void client.getSession().then((result) => {
        if (active && subject.current && (!result.data?.session || result.data.user.id !== subject.current)) clearSession()
      }).catch(() => {})
    }
    const unsubscribe = client.$store.atoms.$sessionSignal.listen(checkSession)
    window.addEventListener('focus', checkSession)
    return () => { active = false; unsubscribe(); window.removeEventListener('focus', checkSession) }
  }, [client])

  if (loading) return <div className={`${styles.routeLoading} ${styles.boot}`} role="status"><LoaderCircle size={20} />Connecting to workspace</div>
  if (!config || (config.mode !== 'local' && !client)) return <div className={`${styles.routeLoading} ${styles.boot}`} role="alert">{error || 'Authentication is unavailable.'}<button type="button" onClick={() => { setLoading(true); setError(''); setRevision((value) => value + 1) }}>Retry connection</button></div>
  if (config.mode !== 'local' && !account && client) return <AuthScreen client={client} connectionError={error} onSignedIn={() => connect(client)} />

  return <AuthContext.Provider value={{
    config, account,
    signOut: async () => {
      if (client) {
        const result = await client.signOut()
        if (result.error) throw new Error(result.error.message || 'Sign-out failed.')
      }
      clearSession()
    },
    refreshAccount: async () => { if (client) await connect(client) },
    sendVerification: async () => {
      if (!client || !account?.user) return
      const result = await client.emailOtp.sendVerificationOtp({ email: account.user.email, type: 'email-verification' })
      if (result.error) throw new Error(result.error.message || 'Verification email could not be requested.')
    },
    verifyEmailCode: async (code) => {
      if (!client || !account?.user) throw new Error('Sign in before verifying your email.')
      const result = await client.emailOtp.verifyEmail({ email: account.user.email, otp: code.trim() })
      if (result.error) throw new Error(result.error.message || 'The verification code was not accepted.')
      const profile = await api.me()
      setAccount(profile)
      if (!profile.user?.email_verified) throw new Error('Verification is still pending. Refresh verification shortly.')
    },
  }}><App key={account?.workspace.id ?? 'local'} /></AuthContext.Provider>
}