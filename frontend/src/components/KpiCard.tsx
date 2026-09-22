// Display one numeric metric with a compact label, icon, and contextual detail.
import type { LucideIcon } from 'lucide-react'
import styles from './KpiCard.module.css'

interface Props { label: string; value: string; detail?: string; icon: LucideIcon; accent?: boolean }

export default function KpiCard({ label, value, detail, icon: Icon, accent = false }: Props) {
  return <section className={styles.card} aria-label={label}>
    <div className={styles.heading}><span>{label}</span><Icon size={16} strokeWidth={1.6} /></div>
    <strong className={`${styles.value} ${accent ? styles.accent : ''} ${value.length > 12 ? styles.compact : ''}`}>{value}</strong>
    {detail && <span className={styles.detail}>{detail}</span>}
  </section>
}