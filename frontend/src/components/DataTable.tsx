// Render typed tabular records with consistent empty and horizontally scrollable states.
import type { ReactNode } from 'react'
import styles from './DataTable.module.css'

export interface Column<T> { id: string; label: string; render: (row: T) => ReactNode }
interface Props<T> { rows: T[]; columns: Column<T>[]; rowKey: (row: T) => string; label: string; emptyText?: string }

export default function DataTable<T>({ rows, columns, rowKey, label, emptyText = 'No matching records' }: Props<T>) {
  return <div className={styles.wrap}>
    <table className={styles.table} aria-label={label}>
      <thead><tr>{columns.map((column) => <th key={column.id} scope="col">{column.label}</th>)}</tr></thead>
      <tbody>{rows.map((row) => <tr key={rowKey(row)}>{columns.map((column) => <td key={column.id}>{column.render(row)}</td>)}</tr>)}</tbody>
    </table>
    {!rows.length && <div className={styles.empty}>{emptyText}</div>}
  </div>
}