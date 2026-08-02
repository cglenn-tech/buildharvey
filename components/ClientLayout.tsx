'use client'
import AgentConnection from './AgentConnection'

/**
 * Client boundary for the root layout.
 * Mounts AgentConnection (which requires useEffect) inside a server layout.
 */
export default function ClientLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AgentConnection />
      {children}
    </>
  )
}
