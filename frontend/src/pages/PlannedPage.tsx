// Keep Phase 11 routes honest without presenting unfinished views or sample data as live.
import { ArrowLeft, Construction } from 'lucide-react'
import { Link } from 'react-router-dom'
import styles from './PlannedPage.module.css'

export default function PlannedPage({ title }: { title: string }) {
  return <section className={styles.page} aria-label={`${title} status`}>
    <Construction size={29} strokeWidth={1.3} />
    <h2>In progress</h2>
    <span>Phase 11</span>
    <Link to="/"><ArrowLeft size={14} />Back to Playground</Link>
  </section>
}