export type Area = {
  id: number
  name: string
  slug: string
  description: string
  center: { lat: number; lng: number }
  bounds: { north: number; south: number; east: number; west: number }
}

export type Coords = { lat: number; lng: number }
export type Theme = 'dark' | 'light'

export type Venue = {
  id: number
  name: string
  slug: string
  type: string
  address: string
  description: string
  price_band: string
  area: { name: string; slug: string }
  opens_at: string
  closes_at: string
  coordinates: Coords
  source: {
    type: string
    url: string | null
    status: string
    confidence: number
    last_verified_at: string
  }
  socials: {
    facebook?: string | null
    instagram?: string | null
    website?: string | null
  }
  next_event_start: string | null
  upcoming_event_count: number
}

export type EventItem = {
  id: number
  title: string
  description: string
  genre: string
  start_at: string
  end_at: string
  price_label: string
  price_amount: number | null
  venue: {
    name: string
    slug: string
    type: string
    address: string
    price_band: string
    opens_at: string
    closes_at: string
    coordinates: Coords
    area: { name: string; slug: string }
  }
  source: {
    type: string
    url: string | null
    status: string
    confidence: number
    last_verified_at: string
  }
}

export type VenueDetail = Venue & {
  opening_hours: Array<{
    day_of_week: number
    open_time: string
    close_time: string
    is_overnight: number
  }>
  events: EventItem[]
}

export type AppConfig = {
  page: 'home' | 'venue' | 'event'
  venueSlug: string | null
  eventId?: number | null
}

export type InitialData = {
  areas?: Area[]
  venues?: Venue[]
  events?: EventItem[]
}

export type Filters = {
  area: string
  genre: string
  venue_type: string
  price_band: string
  date: string
  sort: string
  open_now: boolean
}

export type VenueWithDistance = Venue & { distanceMiles?: number | null }
export type EventWithDistance = EventItem & { distanceMiles?: number | null }
