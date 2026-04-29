import { useEffect, useMemo, useRef, useState } from 'react'

import type { Area, EventItem, Filters, InitialData, Venue, VenueDetail } from './types'

export const initialConfig = window.__APP_CONFIG__ ?? { page: 'home', venueSlug: null, eventId: null }
export const initialData: InitialData = window.__INITIAL_DATA__ ?? {}

type FetchResult<T> = {
  data: T | null
  loading: boolean
  error: string | null
}

export function useFetch<T>(url: string, seed?: T): FetchResult<T> {
  const [data, setData] = useState<T | null>(seed ?? null)
  const [loading, setLoading] = useState(seed === undefined)
  const [error, setError] = useState<string | null>(null)
  const initialRef = useRef(seed)

  useEffect(() => {
    let active = true

    if (initialRef.current !== undefined) {
      initialRef.current = undefined
      return () => {
        active = false
      }
    }

    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`Request failed: ${response.status}`)
        return response.json() as Promise<T>
      })
      .then((json) => {
        if (active) {
          setError(null)
          setData(json)
        }
      })
      .catch((err: Error) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [url])

  return { data, loading, error }
}

export function useDiscoveryData(filters: Filters) {
  const query = useMemo(() => {
    const params = new URLSearchParams()
    Object.entries(filters).forEach(([key, value]) => {
      if (typeof value === 'boolean') {
        if (value) params.set(key, '1')
      } else if (value) {
        params.set(key, value)
      }
    })
    return params.toString()
  }, [filters])

  return {
    areas: useFetch<Area[]>('/api/areas', initialData.areas),
    venues: useFetch<Venue[]>(`/api/venues?${query}`, initialData.venues),
    events: useFetch<EventItem[]>(`/api/events?${query}`, initialData.events),
  }
}

export function useVenueDetail(slug: string) {
  return useFetch<VenueDetail>(`/api/venues/${slug}`)
}

export function useEventDetail(eventId: number) {
  return useFetch<EventItem>(`/api/events/${eventId}`)
}
