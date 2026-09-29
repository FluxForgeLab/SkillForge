import { useEffect, useState } from 'react'

import { eventsWebSocketUrl } from '@/lib/api'

/** Wire payload matching TraceEvent.model_dump(mode="json"). */
export type TraceEventWire = {
  id: string
  run_id: string
  type: string
  timestamp: string
  stage: string | null
  name: string | null
  input: Record<string, unknown>
  output: Record<string, unknown>
  duration_ms: number | null
}

export type EventsConnectionStatus = 'connecting' | 'open' | 'closed' | 'error'

function isTraceEventWire(value: unknown): value is TraceEventWire {
  if (typeof value !== 'object' || value === null) {
    return false
  }
  const record = value as Record<string, unknown>
  return typeof record.id === 'string' && typeof record.type === 'string'
}

/**
 * Subscribe to SkillForge `/api/events` and keep the latest TraceEvents in state.
 * Does not render model chain-of-thought; consumers should show type/name (and
 * input/output only when intentionally displaying those fields).
 */
export function useEvents(
  limit = 100,
  initialEvents: TraceEventWire[] = [],
): {
  events: TraceEventWire[]
  status: EventsConnectionStatus
  error: string | null
} {
  const [events, setEvents] = useState<TraceEventWire[]>(initialEvents)
  const [status, setStatus] = useState<EventsConnectionStatus>('connecting')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const url = eventsWebSocketUrl()
    let closedByCleanup = false
    let socket: WebSocket | null = null
    let retry: number | null = null

    const connect = () => {
      socket = new WebSocket(url)
      socket.addEventListener('open', () => {
        if (!closedByCleanup) {
          setStatus('open')
          setError(null)
        }
      })
      socket.addEventListener('message', (message) => {
        if (typeof message.data !== 'string') {
          return
        }
        if (message.data === 'pong') {
          return
        }
        try {
          const parsed: unknown = JSON.parse(message.data)
          if (!isTraceEventWire(parsed)) {
            return
          }
          setEvents((prev) => {
            const next = [parsed, ...prev]
            return next.length > limit ? next.slice(0, limit) : next
          })
        } catch {
          // Ignore non-JSON control frames.
        }
      })
      socket.addEventListener('error', () => {
        if (!closedByCleanup) {
          setStatus('error')
          setError(`WebSocket error connecting to ${url}`)
        }
      })
      socket.addEventListener('close', () => {
        if (closedByCleanup) {
          return
        }
        setStatus('closed')
        retry = window.setTimeout(connect, 2000)
      })
    }

    connect()

    return () => {
      closedByCleanup = true
      if (retry !== null) {
        window.clearTimeout(retry)
      }
      socket?.close()
    }
  }, [limit])

  return { events, status, error }
}
