// Format precise gateway costs and timings consistently across frontend views.
export function formatCost(value: number): string {
  return value === 0 ? '$0.00' : `$${value.toFixed(6)}`
}

export function formatLatency(milliseconds: number): string {
  return milliseconds < 1000 ? `${Math.round(milliseconds)} ms` : `${(milliseconds / 1000).toFixed(2)} s`
}