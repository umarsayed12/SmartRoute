// Hold auth operations in memory and expose only non-secret workspace state to components.
import { createContext, useContext } from 'react'
import type { VanillaBetterAuthClient } from '@neondatabase/auth'
import type { ClientConfig, WorkspaceAccount } from './types'

export type ManagedAuthClient = VanillaBetterAuthClient

export async function createManagedAuth(url: string): Promise<ManagedAuthClient> {
  const { createAuthClient } = await import('@neondatabase/auth')
  const { BetterAuthVanillaAdapter } = await import('@neondatabase/auth/vanilla/adapters')
  return createAuthClient(url, { adapter: BetterAuthVanillaAdapter() })
}

export interface AuthState {
  config: ClientConfig
  account: WorkspaceAccount | null
  signOut: () => Promise<void>
  refreshAccount: () => Promise<void>
  sendVerification: () => Promise<void>
  verifyEmailCode: (code: string) => Promise<void>
}

export const AuthContext = createContext<AuthState | null>(null)

export function useAuth(): AuthState {
  const state = useContext(AuthContext)
  if (!state) throw new Error('Authentication context is unavailable.')
  return state
}

export async function managedAccessToken(client: ManagedAuthClient, subject: string, onChanged: () => void): Promise<string | null> {
  const session = await client.getSession()
  if (session.error) throw new Error(session.error.message || 'Session could not be refreshed.')
  if (!session.data?.session || session.data.user.id !== subject) { onChanged(); return null }
  const token = session.data?.session?.token
  return typeof token === 'string' && token.split('.').length === 3 ? token : null
}