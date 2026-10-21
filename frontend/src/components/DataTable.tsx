// Render typed tabular records with consistent empty and horizontally scrollable states.
import type { ReactNode } from 'react'
import { LoaderCircle } from 'lucide-react'
import styles from './DataTable.module.css'

export interface Column<T> { id: string; label: string; render: (row: T) => ReactNode }
interface Props<T> {
  rows: T[]
  columns: Column<T>[]
  rowKey: (row: T) => string
  label: string
  emptyText?: string
  loading?: boolean
  loadingText?: string
}

export default function DataTable<T>({
  rows,
  columns,
  rowKey,
  label,
  emptyText = 'No matching records',
  loading = false,
  loadingText = 'Loading...',
}: Props<T>) {
  return (
    <div className={styles.wrap}>
      {loading && <div className={styles.progressBar} aria-hidden="true" />}
      <table className={`${styles.table} ${loading && rows.length > 0 ? styles.loadingTable : ''}`} aria-label={label}>
        <thead><tr>{columns.map((column) => <th key={column.id} scope="col">{column.label}</th>)}</tr></thead>
        <tbody>{rows.map((row) => <tr key={rowKey(row)}>{columns.map((column) => <td key={column.id}>{column.render(row)}</td>)}</tr>)}</tbody>
      </table>
      {!rows.length && (
        <div className={styles.empty}>
          {loading ? (
            <div className={styles.loadingState} role="status">
              <LoaderCircle className={styles.spinner} size={16} />
              <span>{loadingText}</span>
            </div>
          ) : (
            emptyText
          )}
        </div>
      )}
    </div>
  )
}
