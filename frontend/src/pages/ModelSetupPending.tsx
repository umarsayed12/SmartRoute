// Direct workspaces without inference capability to their owned model configuration.
import { LoaderCircle, RefreshCw, ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import ui from './Workspace.module.css'

export default function ModelSetupPending({ verified, loading, error, onRetry }: { verified: boolean; loading: boolean; error: boolean; onRetry: () => void }) {
  return <section className={ui.page}><div className={ui.empty}>
    {loading ? <><LoaderCircle size={20} className={ui.spinner} /><span role="status">Checking workspace setup</span></> : !verified ? <><ShieldCheck size={24} /><div><h2 className={ui.sectionTitle}>Email verification required</h2><Link to="/account" className={ui.primary}>Verify email</Link></div></> : error ? <div role="alert"><h2 className={ui.sectionTitle}>Model configuration unavailable</h2><button type="button" className={ui.button} onClick={onRetry}><RefreshCw size={14} />Retry</button></div> : <><ShieldCheck size={24} /><div><h2 className={ui.sectionTitle}>No enabled workspace model</h2><Link to="/models" className={ui.primary}>Configure models</Link></div></>}
  </div></section>
}