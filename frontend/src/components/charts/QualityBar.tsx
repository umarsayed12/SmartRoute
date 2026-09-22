// Compare positive-feedback fractions while keeping unrated tiers distinct from zero quality.
import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Stats } from '../../types'
import styles from './Charts.module.css'

export default function QualityBar({ quality }: { quality: Stats['quality']['by_tier'] }) {
  const data = (['small', 'medium', 'large'] as const).map((name) => ({
    name, positive: quality[name].positive_rate === null ? null : quality[name].positive_rate * 100,
  }))
  if (data.every((item) => item.positive === null)) return <div className={styles.empty}>No rated answers in this period</div>
  return <div>
    <div className={styles.chart} role="img" aria-label="Positive feedback by final model tier">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 12, right: 8, left: -20, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--border-soft)" />
          <XAxis dataKey="name" axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} tickFormatter={(value: number) => `${value}%`} axisLine={false} tickLine={false} />
          <Tooltip formatter={(value) => [`${Number(value).toFixed(1)}%`, 'Positive']} cursor={false} />
          <Bar dataKey="positive" maxBarSize={44} radius={[3, 3, 0, 0]} isAnimationActive={false}>{data.map((item) => <Cell key={item.name} fill={`var(--${item.name})`} />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
    <div className={styles.legend}>{(['small', 'medium', 'large'] as const).map((tier) => <span key={tier}>{tier}: {quality[tier].count} ratings</span>)}</div>
  </div>
}