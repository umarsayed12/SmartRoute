// Identify the actual model tier with a consistent label and color.
import type { TierName } from '../types'
import styles from './TierBadge.module.css'

export default function TierBadge({ tier }: { tier: TierName }) {
  return <span className={`${styles.badge} ${styles[tier]}`}><span />{tier}</span>
}