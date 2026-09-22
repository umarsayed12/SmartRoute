// Direct workspaces without inference capability to their owned model configuration.
import { ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import ui from './Workspace.module.css'

export default function ModelSetupPending() {
  return <section className={ui.page}><div className={ui.empty}><ShieldCheck size={24} /><div><h2>Workspace model setup required</h2><Link to="/models" className={ui.button}>Configure models</Link></div></div></section>
}