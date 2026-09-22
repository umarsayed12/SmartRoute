// Chart the final-tier request distribution without inventing empty-period values.
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from 'recharts'
import type { TierName } from '../../types'
import styles from './Charts.module.css'

export default function TierPie({ distribution }: { distribution: Record<TierName, number> }) {
  const data = (['small', 'medium', 'large'] as const).map((name) => ({ name, value: distribution[name] }))
  if (!data.some((item) => item.value > 0)) return <div className={styles.empty}>No requests in this period</div>
  return <div>
    <div className={styles.chart} role="img" aria-label={`Tier distribution: ${data.map((item) => `${item.name} ${item.value}`).join(', ')}`}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius={64} outerRadius={93} paddingAngle={3} stroke="none" isAnimationActive={false}>
          {data.map((item) => <Cell key={item.name} fill={`var(--${item.name})`} />)}
        </Pie><Tooltip /></PieChart>
      </ResponsiveContainer>
    </div>
    <div className={styles.legend}>{data.map((item) => <span key={item.name}><i className={`${styles.swatch} ${styles[item.name]}`} />{item.name} <strong>{item.value}</strong></span>)}</div>
  </div>
}