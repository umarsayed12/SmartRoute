// Plot daily saved USD and positive feedback on separate, clearly labelled axes.
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Stats } from '../../types'
import styles from './Charts.module.css'

export default function SavingsLine({ timeline }: { timeline: Stats['timeline'] }) {
  return <div>
    <div className={`${styles.chart} ${styles.tall}`} role="img" aria-label="Daily savings and positive feedback over UTC dates">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={timeline} margin={{ top: 15, right: 0, left: 0, bottom: 5 }}>
          <CartesianGrid vertical={false} stroke="var(--border-soft)" />
          <XAxis dataKey="date" tickFormatter={(value: string) => value.slice(5)} minTickGap={24} axisLine={false} tickLine={false} />
          <YAxis yAxisId="cost" width={62} tickFormatter={(value: number) => `$${value.toLocaleString(undefined, { maximumFractionDigits: 4 })}`} axisLine={false} tickLine={false} />
          <YAxis yAxisId="quality" orientation="right" width={40} domain={[0, 1]} tickFormatter={(value: number) => `${Math.round(value * 100)}%`} axisLine={false} tickLine={false} />
          <Tooltip formatter={(value, name) => [name === 'Saved USD' ? `$${Number(value).toFixed(6)}` : `${(Number(value) * 100).toFixed(1)}%`, name]} />
          <Line yAxisId="cost" dataKey="saved_usd" name="Saved USD" stroke="var(--medium)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line yAxisId="quality" dataKey="positive_rate" name="Positive feedback" stroke="var(--accent)" strokeWidth={2} strokeDasharray="4 4" dot={{ r: 2 }} connectNulls={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
    <div className={styles.legend}><span><i className={`${styles.swatch} ${styles.medium}`} />Saved USD</span><span><i className={`${styles.swatch} ${styles.small}`} />Positive feedback</span></div>
  </div>
}