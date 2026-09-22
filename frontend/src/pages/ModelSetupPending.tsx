// Keep authenticated preview from implying that shared local models are available.
import { ShieldCheck } from 'lucide-react'
import { Link } from 'react-router-dom'
import ui from './Workspace.module.css'

export default function ModelSetupPending() {
  return <section className={ui.page}><div className={ui.empty}><ShieldCheck size={24} /><div><h2>Workspace model setup pending</h2><p className={ui.muted}>Provider routing checkpoint M3</p><Link to="/account" className={ui.button}>Workspace and API keys</Link></div></div></section>
}