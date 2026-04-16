import { useMemo, useRef, useState, type FormEvent } from 'react'

import { initialConfig, useDiscoveryData, useEventDetail, useVenueDetail } from './api'
import { classNames, DAY_LABELS, distanceMiles, formatDateTime, formatDistance, mapsUrl } from './lib'
import type { Area, Coords, EventWithDistance, Filters, Theme, VenueWithDistance } from './types'

function useCurrentLocation() {
  const [coords, setCoords] = useState<Coords | null>(null)
  const [error, setError] = useState<string | null>(null)

  function requestLocation() {
    if (!navigator.geolocation) {
      setError('Geolocation is not available in this browser.')
      return
    }

    navigator.geolocation.getCurrentPosition(
      (position) => setCoords({ lat: position.coords.latitude, lng: position.coords.longitude }),
      () => setError('Location permission was blocked.'),
      { enableHighAccuracy: true, timeout: 10000 },
    )
  }

  return { coords, error, requestLocation }
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem('tnf-theme')
    return saved === 'light' || saved === 'dark' ? saved : 'dark'
  })

  useMemo(() => {
    document.body.setAttribute('data-theme', theme)
    window.localStorage.setItem('tnf-theme', theme)
  }, [theme])

  return {
    theme,
    toggleTheme: () => setTheme((current) => (current === 'dark' ? 'light' : 'dark')),
  }
}

function Header({
  theme,
  hasLocation,
  onToggleTheme,
  onUseLocation,
}: {
  theme: Theme
  hasLocation: boolean
  onToggleTheme: () => void
  onUseLocation: () => void
}) {
  return (
    <header className="app-header">
      <a className="app-brand" href="/">
        <span className="brand-badge">TN</span>
        <span>
          <strong>Town Nightlife Finder</strong>
          <small>Map it, sort it, and stay in the flow</small>
        </span>
      </a>
      <nav className="app-nav">
        <a href="/">Explore town</a>
        <a href="/login">Admin / Owner</a>
        <button className="theme-toggle" type="button" onClick={onUseLocation}>
          {hasLocation ? 'Location on' : 'Use location'}
        </button>
        <button className="theme-toggle" type="button" onClick={onToggleTheme}>
          {theme === 'dark' ? 'Bright mode' : 'Dark mode'}
        </button>
      </nav>
    </header>
  )
}

function SkylineGraphic() {
  return (
    <svg className="hero-art nightlife-scene" viewBox="0 0 640 360" aria-hidden="true">
      <defs>
        <linearGradient id="sceneSky" x1="0%" x2="100%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="rgba(255,255,255,0.18)" />
          <stop offset="100%" stopColor="rgba(255,255,255,0.02)" />
        </linearGradient>
        <linearGradient id="sceneGlow" x1="10%" x2="90%" y1="0%" y2="100%">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.95" />
          <stop offset="55%" stopColor="var(--accent-2)" stopOpacity="0.85" />
          <stop offset="100%" stopColor="var(--accent-3)" stopOpacity="0.88" />
        </linearGradient>
      </defs>
      <rect x="0" y="0" width="640" height="360" fill="url(#sceneSky)" />
      <circle cx="130" cy="92" r="78" fill="url(#sceneGlow)" opacity="0.18" />
      <circle cx="520" cy="74" r="66" fill="var(--accent-3)" opacity="0.16" />
      <path d="M0 252H56V196H82V226H118V174H160V208H188V160H240V222H280V150H326V184H360V138H402V212H436V168H472V188H516V156H548V212H580V184H640V360H0Z" fill="rgba(255,255,255,0.09)" />
      <path d="M0 284H40V214H74V244H108V190H148V166H188V236H226V182H264V128H304V248H344V178H386V204H422V154H468V236H504V176H548V142H586V224H640V360H0Z" fill="rgba(8,15,31,0.86)" />
      <path d="M0 266C58 284 120 288 186 270C252 252 294 230 364 236C452 244 530 296 640 272V360H0Z" fill="rgba(50,195,255,0.12)" />
    </svg>
  )
}

function AppBackground() {
  return (
    <div className="app-background-art" aria-hidden="true">
      <SkylineGraphic />
    </div>
  )
}

function SidePanel({
  selectedEvent,
  selectedVenue,
  onClose,
}: {
  selectedEvent: EventWithDistance | null
  selectedVenue: VenueWithDistance | null
  onClose: () => void
}) {
  if (!selectedEvent && !selectedVenue) return null

  const title = selectedEvent ? selectedEvent.title : selectedVenue!.name
  const distance = selectedEvent?.distanceMiles ?? selectedVenue?.distanceMiles ?? null
  const destination = selectedEvent?.venue.coordinates ?? selectedVenue?.coordinates

  return (
    <>
      <button className="panel-scrim" type="button" onClick={onClose} aria-label="Close panel" />
      <aside className="side-panel">
        <button className="side-panel-close" type="button" onClick={onClose}>
          x
        </button>
        <div className="side-panel-ribbon" />
        <p className="side-panel-kicker">
          {selectedEvent
            ? `${selectedEvent.genre} event`
            : `${selectedVenue?.type} in ${selectedVenue?.area.name}`}
        </p>
        <h2>{title}</h2>
        <p className="side-panel-copy">
          {selectedEvent ? selectedEvent.description : selectedVenue?.description}
        </p>
        <div className="side-stat-grid">
          <div>
            <strong>{formatDistance(distance)}</strong>
            <span>From your location</span>
          </div>
          <div>
            <strong>{selectedEvent ? selectedEvent.price_label : selectedVenue?.price_band}</strong>
            <span>{selectedEvent ? 'Price' : 'Budget'}</span>
          </div>
          <div>
            <strong>
              {selectedEvent
                ? formatDateTime(selectedEvent.start_at, {
                    day: '2-digit',
                    month: 'short',
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                : `${selectedVenue?.opens_at} - ${selectedVenue?.closes_at}`}
            </strong>
            <span>{selectedEvent ? 'Starts' : 'Open today'}</span>
          </div>
          <div>
            <strong>{selectedEvent ? selectedEvent.venue.name : selectedVenue?.area.name}</strong>
            <span>{selectedEvent ? 'Venue' : 'Area'}</span>
          </div>
        </div>
        <div className="side-detail-list">
          {selectedEvent ? (
            <>
              <div>
                <span>Address</span>
                <strong>{selectedEvent.venue.address}</strong>
              </div>
              <div>
                <span>Venue hours</span>
                <strong>
                  {selectedEvent.venue.opens_at} - {selectedEvent.venue.closes_at}
                </strong>
              </div>
              <div>
                <span>Source freshness</span>
                <strong>
                  {selectedEvent.source.status} | {Math.round(selectedEvent.source.confidence * 100)}%
                </strong>
              </div>
            </>
          ) : (
            <>
              <div>
                <span>Address</span>
                <strong>{selectedVenue?.address}</strong>
              </div>
              <div>
                <span>Upcoming events</span>
                <strong>{selectedVenue?.upcoming_event_count} published</strong>
              </div>
              <div>
                <span>Source freshness</span>
                <strong>
                  {selectedVenue?.source.status} | {Math.round((selectedVenue?.source.confidence ?? 0) * 100)}%
                </strong>
              </div>
            </>
          )}
        </div>
        {destination ? (
          <div className="action-row side-actions">
            <a className="inline-route" href={mapsUrl(destination)} target="_blank" rel="noreferrer">
              Directions
            </a>
            {selectedEvent ? (
              <a className="inline-route subtle" href={`/events/${selectedEvent.id}`}>
                Full event page
              </a>
            ) : null}
            {selectedVenue ? (
              <a className="inline-route subtle" href={`/venues/${selectedVenue.slug}`}>
                Full venue page
              </a>
            ) : null}
          </div>
        ) : null}
      </aside>
    </>
  )
}
function MapPanel({
  areas,
  venues,
  events,
  selectedArea,
  selectedEventId,
  selectedVenueId,
  onSelectArea,
  onSelectEvent,
  onSelectVenue,
}: {
  areas: Area[]
  venues: VenueWithDistance[]
  events: EventWithDistance[]
  selectedArea: string
  selectedEventId: number | null
  selectedVenueId: number | null
  onSelectArea: (slug: string) => void
  onSelectEvent: (event: EventWithDistance) => void
  onSelectVenue: (venue: VenueWithDistance) => void
}) {
  const [pan, setPan] = useState({ x: 0, y: 0 })
  const [dragging, setDragging] = useState(false)
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number; moved: boolean } | null>(null)

  if (!areas.length) return null

  const north = Math.max(...areas.map((area) => area.bounds.north))
  const south = Math.min(...areas.map((area) => area.bounds.south))
  const east = Math.max(...areas.map((area) => area.bounds.east))
  const west = Math.min(...areas.map((area) => area.bounds.west))

  function startDrag(clientX: number, clientY: number) {
    dragRef.current = { x: clientX, y: clientY, panX: pan.x, panY: pan.y, moved: false }
    setDragging(false)
  }

  function updateDrag(clientX: number, clientY: number) {
    if (!dragRef.current) return
    const deltaX = clientX - dragRef.current.x
    const deltaY = clientY - dragRef.current.y
    const moved = Math.abs(deltaX) > 6 || Math.abs(deltaY) > 6
    if (!moved && !dragRef.current.moved) return
    dragRef.current.moved = true
    setDragging(true)
    setPan({
      x: Math.max(-140, Math.min(140, dragRef.current.panX + deltaX)),
      y: Math.max(-110, Math.min(110, dragRef.current.panY + deltaY)),
    })
  }

  function consumeDragClick() {
    if (!dragRef.current?.moved) return false
    dragRef.current = null
    setDragging(false)
    return true
  }

  function endDrag() {
    dragRef.current = null
    setDragging(false)
  }

  return (
    <div className="hero-panel district-panel">
      <div className="section-topline">
        <span>Town map</span>
        <small>Drag to explore and tap an event pulse for live info</small>
      </div>
      <div
        className={classNames('map-board', dragging && 'dragging')}
        onMouseDown={(event) => startDrag(event.clientX, event.clientY)}
        onMouseMove={(event) => updateDrag(event.clientX, event.clientY)}
        onMouseUp={endDrag}
        onMouseLeave={endDrag}
        onTouchStart={(event) => {
          const touch = event.touches[0]
          if (touch) startDrag(touch.clientX, touch.clientY)
        }}
        onTouchMove={(event) => {
          const touch = event.touches[0]
          if (touch) updateDrag(touch.clientX, touch.clientY)
        }}
        onTouchEnd={endDrag}
      >
        <div className="map-canvas" style={{ transform: `translate(${pan.x}px, ${pan.y}px)` }}>
          {areas.map((area, index) => {
            const left = ((area.center.lng - west) / (east - west)) * 100
            const top = 100 - ((area.center.lat - south) / (north - south)) * 100
            return (
              <button
                key={area.id}
                className={classNames(
                  'map-area-chip',
                  selectedArea === area.slug && 'active',
                  `district-tone-${(index % 3) + 1}`,
                )}
                style={{ left: `${left}%`, top: `${top}%` }}
                onClick={() => {
                  if (consumeDragClick()) return
                  onSelectArea(selectedArea === area.slug ? '' : area.slug)
                }}
              >
                {area.name}
              </button>
            )
          })}
          {venues.map((venue) => {
            const left = ((venue.coordinates.lng - west) / (east - west)) * 100
            const top = 100 - ((venue.coordinates.lat - south) / (north - south)) * 100
            return (
              <button
                key={venue.id}
                type="button"
                className={classNames('map-pin', 'map-pin-button', selectedVenueId === venue.id && 'active')}
                style={{ left: `${left}%`, top: `${top}%` }}
                onClick={(event) => {
                  event.stopPropagation()
                  if (consumeDragClick()) return
                  onSelectVenue(venue)
                }}
              >
                <span>{venue.name}</span>
              </button>
            )
          })}
          {events.map((item) => {
            const left = ((item.venue.coordinates.lng - west) / (east - west)) * 100
            const top = 100 - ((item.venue.coordinates.lat - south) / (north - south)) * 100
            return (
              <button
                key={item.id}
                type="button"
                className={classNames('event-pin', selectedEventId === item.id && 'active')}
                style={{ left: `${left}%`, top: `${top}%` }}
                onClick={(event) => {
                  event.stopPropagation()
                  if (consumeDragClick()) return
                  onSelectEvent(item)
                }}
              >
                <span>{item.title}</span>
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

function HomePage() {
  const { theme, toggleTheme } = useTheme()
  const location = useCurrentLocation()
  const [filters, setFilters] = useState<Filters>({
    area: '',
    genre: '',
    venue_type: '',
    price_band: '',
    date: '',
    sort: 'time',
    open_now: false,
  })
  const [activeTab, setActiveTab] = useState<'all' | 'nearby'>('all')
  const [selectedEvent, setSelectedEvent] = useState<EventWithDistance | null>(null)
  const [selectedVenue, setSelectedVenue] = useState<VenueWithDistance | null>(null)
  const { areas, venues, events } = useDiscoveryData(filters)

  const venueData = venues.data ?? []
  const eventData = events.data ?? []
  const areaData = areas.data ?? []

  const genres = useMemo(() => Array.from(new Set(eventData.map((item) => item.genre))).sort(), [eventData])
  const venueTypes = useMemo(() => Array.from(new Set(venueData.map((item) => item.type))).sort(), [venueData])
  const priceBands = useMemo(() => Array.from(new Set(venueData.map((item) => item.price_band))).sort(), [venueData])

  const venuesWithDistance = useMemo(
    () =>
      venueData.map((venue) => ({
        ...venue,
        distanceMiles: location.coords ? distanceMiles(location.coords, venue.coordinates) : null,
      })),
    [venueData, location.coords],
  )

  const allEventsWithDistance = useMemo(
    () =>
      eventData.map((item) => ({
        ...item,
        distanceMiles: location.coords ? distanceMiles(location.coords, item.venue.coordinates) : null,
      })),
    [eventData, location.coords],
  )

  const nearbyEvents = useMemo(
    () =>
      allEventsWithDistance
        .filter((item) => item.distanceMiles !== null)
        .sort((left, right) => (left.distanceMiles ?? 0) - (right.distanceMiles ?? 0))
        .slice(0, 8),
    [allEventsWithDistance],
  )

  const displayedEvents = activeTab === 'nearby' ? nearbyEvents : allEventsWithDistance
  const spotlight = venuesWithDistance[0] ?? null

  return (
    <div className="nightlife-app">
      <AppBackground />
      <Header
        theme={theme}
        hasLocation={Boolean(location.coords)}
        onToggleTheme={toggleTheme}
        onUseLocation={location.requestLocation}
      />
      <section className="hero-shell hero-shell-rich">
        <div className="hero-panel hero-copy hero-copy-rich">
          <div className="hero-copy-content">
            <p className="kicker">Town nightlife planner</p>
            <h1>Stay on the page. Explore the night through a richer interactive map.</h1>
            <p className="lede">
              Browse venues and events, tap map pulses, and open a side panel with more
              information instead of losing your place.
            </p>
            <div className="hero-metrics">
              <div><strong>{venuesWithDistance.length}</strong><span>venues matching now</span></div>
              <div><strong>{allEventsWithDistance.length}</strong><span>events in the schedule</span></div>
              <div><strong>{location.coords ? nearbyEvents.length : 0}</strong><span>nearby picks ready</span></div>
            </div>
            {spotlight ? (
              <button
                type="button"
                className="spotlight-banner spotlight-button"
                onClick={() => {
                  setSelectedVenue(spotlight)
                  setSelectedEvent(null)
                }}
              >
                <span className="spotlight-label">Spotlight</span>
                <div>
                  <strong>{spotlight.name}</strong>
                  <p>
                    {spotlight.area.name} | {spotlight.opens_at} - {spotlight.closes_at} |{' '}
                    {formatDistance(spotlight.distanceMiles)}
                  </p>
                </div>
                <span className="cta-link">Open panel</span>
              </button>
            ) : null}
          </div>
        </div>
        <MapPanel
          areas={areaData}
          venues={venuesWithDistance}
          events={allEventsWithDistance}
          selectedArea={filters.area}
          selectedEventId={selectedEvent?.id ?? null}
          selectedVenueId={selectedVenue?.id ?? null}
          onSelectArea={(slug) => setFilters((current) => ({ ...current, area: slug }))}
          onSelectEvent={(event) => {
            setSelectedEvent(event)
            setSelectedVenue(null)
          }}
          onSelectVenue={(venue) => {
            setSelectedVenue(venue)
            setSelectedEvent(null)
          }}
        />
      </section>
      <section className="filter-surface">
        <div className="section-topline">
          <span>Filter the night</span>
          <small>Sort by vibe, spend, timing, or what is near you</small>
        </div>
        <div className="filter-grid">
          <label>
            Date
            <input type="date" value={filters.date} onChange={(event) => setFilters({ ...filters, date: event.target.value })} />
          </label>
          <label>
            Genre
            <select value={filters.genre} onChange={(event) => setFilters({ ...filters, genre: event.target.value })}>
              <option value="">Any genre</option>
              {genres.map((genre) => <option key={genre} value={genre}>{genre}</option>)}
            </select>
          </label>
          <label>
            Venue type
            <select value={filters.venue_type} onChange={(event) => setFilters({ ...filters, venue_type: event.target.value })}>
              <option value="">Any venue</option>
              {venueTypes.map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
          </label>
          <label>
            Price band
            <select value={filters.price_band} onChange={(event) => setFilters({ ...filters, price_band: event.target.value })}>
              <option value="">Any budget</option>
              {priceBands.map((band) => <option key={band} value={band}>{band}</option>)}
            </select>
          </label>
          <label>
            Sort by
            <select value={filters.sort} onChange={(event) => setFilters({ ...filters, sort: event.target.value })}>
              <option value="time">Next event / opening time</option>
              <option value="name">Venue name</option>
              <option value="price">Price</option>
              <option value="area">Area</option>
            </select>
          </label>
          <label className="toggle-field">
            <span>Open now</span>
            <button className={classNames('toggle-pill', filters.open_now && 'active')} type="button" onClick={() => setFilters({ ...filters, open_now: !filters.open_now })}>
              <span />
            </button>
          </label>
        </div>
      </section>
      {areas.error || venues.error || events.error ? (
        <section className="filter-surface">
          <p className="error-note">Data load issue: {[areas.error, venues.error, events.error].filter(Boolean).join(' | ')}</p>
        </section>
      ) : null}
      <section className="events-toolbar">
        <div className="tab-group">
          <button className={classNames('tab-button', activeTab === 'all' && 'active')} onClick={() => setActiveTab('all')}>All events</button>
          <button className={classNames('tab-button', activeTab === 'nearby' && 'active')} onClick={() => { setActiveTab('nearby'); if (!location.coords) location.requestLocation() }}>Events close by</button>
        </div>
        <div className="nearby-state">
          {location.coords ? <span>Nearby results use your current location.</span> : <span>{location.error ?? 'Enable location to show exact distance from you.'}</span>}
        </div>
      </section>
      <section className="listing-grid">
        <div className="listing-column">
          <div className="section-headline"><h2>Venues in view</h2><p>Tap any venue card to open details in a side panel.</p></div>
          {venues.loading ? <p className="empty-message">Loading venues...</p> : null}
          {!venues.loading && !venueData.length ? <p className="empty-message">No venues match the current filters.</p> : null}
          <div className="card-stack">
            {venuesWithDistance.map((venue) => (
              <button key={venue.id} type="button" className="venue-tile tile-button" onClick={() => { setSelectedVenue(venue); setSelectedEvent(null) }}>
                <div className="tile-accent tile-accent-venue" />
                <div className="tile-topline"><span>{venue.type}</span><span>{venue.area.name}</span><span>{venue.price_band}</span></div>
                <h3>{venue.name}</h3>
                <p>{venue.description}</p>
                <dl className="data-points">
                  <div><dt>Hours</dt><dd>{venue.opens_at} - {venue.closes_at}</dd></div>
                  <div><dt>Address</dt><dd>{venue.address}</dd></div>
                  <div><dt>Next event</dt><dd>{formatDateTime(venue.next_event_start)}</dd></div>
                  <div><dt>Distance</dt><dd>{formatDistance(venue.distanceMiles)}</dd></div>
                  <div><dt>Freshness</dt><dd>{venue.source.status} | {Math.round(venue.source.confidence * 100)}%</dd></div>
                </dl>
              </button>
            ))}
          </div>
        </div>
        <div className="listing-column">
          <div className="section-headline"><h2>{activeTab === 'nearby' ? 'Events close by' : 'Upcoming events'}</h2><p>Tap any event card to open a richer side panel instead of another page.</p></div>
          {events.loading ? <p className="empty-message">Loading events...</p> : null}
          {!events.loading && !displayedEvents.length ? <p className="empty-message">No events match the current filters.</p> : null}
          <div className="card-stack">
            {displayedEvents.map((item) => (
              <button key={item.id} type="button" className="event-tile tile-button" onClick={() => { setSelectedEvent(item); setSelectedVenue(null) }}>
                <div className="tile-accent tile-accent-event" />
                <div className="tile-topline"><span>{item.genre}</span><span>{item.venue.name}</span><span>{item.price_label}</span></div>
                <h3>{item.title}</h3>
                <p>{item.description}</p>
                <dl className="data-points">
                  <div><dt>Starts</dt><dd>{formatDateTime(item.start_at)}</dd></div>
                  <div><dt>Venue hours</dt><dd>{item.venue.opens_at} - {item.venue.closes_at}</dd></div>
                  <div><dt>Area</dt><dd>{item.venue.area.name}</dd></div>
                  <div><dt>Distance</dt><dd>{formatDistance(item.distanceMiles)}</dd></div>
                  <div><dt>Source</dt><dd>{item.source.status} | {formatDateTime(item.source.last_verified_at, { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}</dd></div>
                </dl>
              </button>
            ))}
          </div>
        </div>
      </section>
      <SidePanel selectedEvent={selectedEvent} selectedVenue={selectedVenue} onClose={() => { setSelectedEvent(null); setSelectedVenue(null) }} />
    </div>
  )
}

function VenuePage({ slug }: { slug: string }) {
  const { theme, toggleTheme } = useTheme()
  const location = useCurrentLocation()
  const { data, loading, error } = useVenueDetail(slug)
  const [claim, setClaim] = useState({ claimant_name: '', claimant_email: '', message: '' })
  const [claimState, setClaimState] = useState<{ loading: boolean; message: string | null; error: string | null }>({ loading: false, message: null, error: null })

  async function submitClaim(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!data) return
    setClaimState({ loading: true, message: null, error: null })
    const response = await fetch('/claims', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ venue_id: data.id, ...claim }),
    })
    const payload = (await response.json()) as { message?: string; error?: string }
    if (!response.ok) {
      setClaimState({ loading: false, message: null, error: payload.error ?? 'Claim failed.' })
      return
    }
    setClaim({ claimant_name: '', claimant_email: '', message: '' })
    setClaimState({ loading: false, message: payload.message ?? 'Claim submitted.', error: null })
  }

  return (
    <div className="nightlife-app">
      <AppBackground />
      <Header theme={theme} hasLocation={Boolean(location.coords)} onToggleTheme={toggleTheme} onUseLocation={location.requestLocation} />
      <a className="back-link" href="/">Back to town view</a>
      {loading ? <p className="empty-message">Loading venue...</p> : null}
      {error ? <p className="empty-message">{error}</p> : null}
      {data ? (
        <>
          <section className="venue-hero venue-hero-rich">
            <div className="hero-panel venue-main">
              <p className="kicker">{data.type} | {data.area.name}</p>
              <h1>{data.name}</h1>
              <p className="lede">{data.description}</p>
              <div className="pill-row"><span>{data.price_band}</span><span>{data.opens_at} - {data.closes_at}</span><span>{data.source.status}</span><span>{formatDistance(location.coords ? distanceMiles(location.coords, data.coordinates) : null)}</span></div>
            </div>
          </section>
          <section className="listing-grid">
            <div className="listing-column">
              <div className="section-headline"><h2>Opening hours</h2><p>Overnight sessions are called out clearly.</p></div>
              <div className="card-stack">
                {data.opening_hours.map((hour) => (
                  <div key={hour.day_of_week} className="hour-row">
                    <span>{DAY_LABELS[hour.day_of_week]}</span>
                    <strong>{hour.open_time} - {hour.close_time}{hour.is_overnight ? ' overnight' : ''}</strong>
                  </div>
                ))}
              </div>
            </div>
            <div className="listing-column">
              <div className="section-headline"><h2>Published events</h2><p>Detailed event pages are still available from the venue profile.</p></div>
              <div className="card-stack">
                {data.events.map((item) => (
                  <article key={item.id} className="event-tile">
                    <div className="tile-accent tile-accent-event" />
                    <div className="tile-topline"><span>{item.genre}</span><span>{item.price_label}</span></div>
                    <h3>{item.title}</h3>
                    <p>{item.description}</p>
                    <p className="mini-copy">{formatDateTime(item.start_at)} to {formatDateTime(item.end_at, { hour: '2-digit', minute: '2-digit' })}</p>
                  </article>
                ))}
              </div>
            </div>
          </section>
          <section className="claim-surface">
            <div className="section-headline"><h2>Claim this venue</h2><p>Venue teams can request ownership so they can keep listings fresh.</p></div>
            <form className="claim-grid" onSubmit={submitClaim}>
              <label>Name<input value={claim.claimant_name} onChange={(event) => setClaim({ ...claim, claimant_name: event.target.value })} required /></label>
              <label>Email<input type="email" value={claim.claimant_email} onChange={(event) => setClaim({ ...claim, claimant_email: event.target.value })} required /></label>
              <label className="claim-message">Message<textarea rows={4} value={claim.message} onChange={(event) => setClaim({ ...claim, message: event.target.value })} required /></label>
              <button type="submit" disabled={claimState.loading}>{claimState.loading ? 'Submitting...' : 'Submit claim request'}</button>
            </form>
            {claimState.message ? <p className="success-note">{claimState.message}</p> : null}
            {claimState.error ? <p className="error-note">{claimState.error}</p> : null}
          </section>
        </>
      ) : null}
    </div>
  )
}

function EventPage({ eventId }: { eventId: number }) {
  const { theme, toggleTheme } = useTheme()
  const location = useCurrentLocation()
  const { data, loading, error } = useEventDetail(eventId)

  return (
    <div className="nightlife-app">
      <AppBackground />
      <Header theme={theme} hasLocation={Boolean(location.coords)} onToggleTheme={toggleTheme} onUseLocation={location.requestLocation} />
      <a className="back-link" href="/">Back to town view</a>
      {loading ? <p className="empty-message">Loading event...</p> : null}
      {error ? <p className="empty-message">{error}</p> : null}
      {data ? (
        <section className="event-detail-grid">
          <div className="spotlight-card">
            <div className="section-headline"><h2>{data.title}</h2><p>{data.description}</p></div>
            <dl className="data-points">
              <div><dt>Starts</dt><dd>{formatDateTime(data.start_at)}</dd></div>
              <div><dt>Ends</dt><dd>{formatDateTime(data.end_at, { weekday: 'short', hour: '2-digit', minute: '2-digit' })}</dd></div>
              <div><dt>Venue</dt><dd>{data.venue.name}</dd></div>
              <div><dt>Directions</dt><dd><a className="inline-route" href={mapsUrl(data.venue.coordinates)} target="_blank" rel="noreferrer">Open route</a></dd></div>
            </dl>
          </div>
        </section>
      ) : null}
    </div>
  )
}

export default function App() {
  if (initialConfig.page === 'venue' && initialConfig.venueSlug) return <VenuePage slug={initialConfig.venueSlug} />
  if (initialConfig.page === 'event' && initialConfig.eventId) return <EventPage eventId={initialConfig.eventId} />
  return <HomePage />
}
