import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

import { initialConfig, useDiscoveryData, useEventDetail, useVenueDetail } from './api'
import { classNames, DAY_LABELS, distanceMiles, formatDateTime, formatDistance, mapsUrl } from './lib'
import type { Area, Coords, EventWithDistance, Filters, Theme, VenueWithDistance } from './types'

type TownSearchResult = {
  place_id: number
  display_name: string
  lat: string
  lon: string
  boundingbox?: string[]
}

const DEFAULT_TOWN = {
  label: 'Ballina, Co. Mayo',
  coords: { lat: 54.1159, lng: -9.1536 },
}

const EVENT_MARKER_SVG = `
  <svg class="event-marker-svg" viewBox="0 0 64 78" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="eventPinGlow" x1="10%" x2="90%" y1="0%" y2="100%">
        <stop offset="0%" stop-color="#ff7a29" />
        <stop offset="54%" stop-color="#f4c95d" />
        <stop offset="100%" stop-color="#32c3ff" />
      </linearGradient>
    </defs>
    <path class="event-pin-shadow" d="M32 76C22 60 8 50 8 28C8 12 18 3 32 3s24 9 24 25c0 22-14 32-24 48Z" />
    <path class="event-pin-body" d="M32 72C22 56 10 48 10 28C10 13 19 5 32 5s22 8 22 23c0 20-12 28-22 44Z" />
    <circle class="event-pin-inner" cx="32" cy="29" r="15" />
    <path class="event-pin-note" d="M37 18v20.5a5.5 5.5 0 1 1-3-4.9V23l-12 3v14.5a5.5 5.5 0 1 1-3-4.9V23.7L37 18Z" />
  </svg>
`

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
    return saved === 'light' || saved === 'dark' ? saved : 'light'
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
  hasLocation,
  onClose,
  onShowEventRoute,
}: {
  selectedEvent: EventWithDistance | null
  selectedVenue: VenueWithDistance | null
  hasLocation: boolean
  onClose: () => void
  onShowEventRoute: (event: EventWithDistance) => void
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
            {selectedEvent ? (
              <button className="inline-route side-route-button" type="button" onClick={() => onShowEventRoute(selectedEvent)}>
                {hasLocation ? 'Show route in app' : 'Use location for route'}
              </button>
            ) : null}
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
  userCoords,
  routeTarget,
  onSelectArea,
}: {
  areas: Area[]
  venues: VenueWithDistance[]
  events: EventWithDistance[]
  selectedArea: string
  selectedEventId: number | null
  selectedVenueId: number | null
  userCoords: Coords | null
  routeTarget: EventWithDistance | null
  onSelectArea: (slug: string) => void
}) {
  const mapElementRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerLayerRef = useRef<L.LayerGroup | null>(null)
  const routeLayerRef = useRef<L.LayerGroup | null>(null)
  const hasFittedInitialMarkers = useRef(false)
  const [townQuery, setTownQuery] = useState('')
  const [townResults, setTownResults] = useState<TownSearchResult[]>([])
  const [selectedTown, setSelectedTown] = useState(DEFAULT_TOWN.label)
  const [townSearchStatus, setTownSearchStatus] = useState<'idle' | 'loading' | 'error' | 'empty'>('idle')

  useEffect(() => {
    if (!mapElementRef.current || mapRef.current) return

    const map = L.map(mapElementRef.current, {
      center: [DEFAULT_TOWN.coords.lat, DEFAULT_TOWN.coords.lng],
      zoom: 16,
      zoomControl: true,
      scrollWheelZoom: true,
    })

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors',
      maxZoom: 19,
    }).addTo(map)

    routeLayerRef.current = L.layerGroup().addTo(map)
    markerLayerRef.current = L.layerGroup().addTo(map)
    mapRef.current = map

    window.setTimeout(() => map.invalidateSize(), 80)

    return () => {
      map.remove()
      mapRef.current = null
      markerLayerRef.current = null
      routeLayerRef.current = null
    }
  }, [])

  useEffect(() => {
    const map = mapRef.current
    const layer = markerLayerRef.current
    if (!map || !layer) return

    layer.clearLayers()

    if (!userCoords) {
      routeLayerRef.current?.clearLayers()
    }

    const venueIcon = (active: boolean) =>
      L.divIcon({
        className: classNames('leaflet-night-marker', 'venue-leaflet-marker', active && 'active'),
        html: '<span class="marker-glow"></span><span class="marker-core"></span>',
        iconSize: [34, 34],
        iconAnchor: [17, 17],
      })

    const eventIcon = (active: boolean) =>
      L.divIcon({
        className: classNames('leaflet-night-marker', 'event-leaflet-marker', active && 'active'),
        html: `<span class="marker-glow"></span>${EVENT_MARKER_SVG}`,
        iconSize: [48, 58],
        iconAnchor: [24, 54],
      })

    const venuePopup = (venue: VenueWithDistance) => {
      const popup = document.createElement('div')
      popup.className = 'event-map-popup venue-map-popup'

      const kicker = document.createElement('p')
      kicker.className = 'event-map-popup-kicker'
      kicker.textContent = `${venue.type} | ${venue.price_band}`

      const title = document.createElement('strong')
      title.textContent = venue.name

      const meta = document.createElement('span')
      meta.textContent = `${venue.address} | ${venue.opens_at} - ${venue.closes_at}`

      const directions = document.createElement('a')
      directions.href = mapsUrl(venue.coordinates)
      directions.target = '_blank'
      directions.rel = 'noreferrer'
      directions.textContent = 'Open in maps'

      popup.append(kicker, title, meta, directions)
      return popup
    }

    const drawSimpleRoute = (item: EventWithDistance) => {
      if (!userCoords || !routeLayerRef.current) return

      const start = L.latLng(userCoords.lat, userCoords.lng)
      const destination = L.latLng(item.venue.coordinates.lat, item.venue.coordinates.lng)

      routeLayerRef.current.clearLayers()
      L.polyline([start, destination], {
        className: 'simple-route-line',
        color: '#32c3ff',
        weight: 5,
        opacity: 0.92,
        dashArray: '10 12',
        lineCap: 'round',
      }).addTo(routeLayerRef.current)

      L.circleMarker(start, {
        className: 'simple-route-start',
        radius: 8,
        color: '#fff9ef',
        fillColor: '#32c3ff',
        fillOpacity: 1,
        weight: 3,
      }).addTo(routeLayerRef.current)

      L.circleMarker(destination, {
        className: 'simple-route-finish',
        radius: 9,
        color: '#fff9ef',
        fillColor: '#ff7a29',
        fillOpacity: 1,
        weight: 3,
      }).addTo(routeLayerRef.current)

      map.fitBounds(L.latLngBounds([start, destination]).pad(0.25), { maxZoom: 17 })
    }

    const eventPopup = (item: EventWithDistance) => {
      const popup = document.createElement('div')
      popup.className = 'event-map-popup'

      const kicker = document.createElement('p')
      kicker.className = 'event-map-popup-kicker'
      kicker.textContent = `${item.genre} | ${item.price_label}`

      const title = document.createElement('strong')
      title.textContent = item.title

      const meta = document.createElement('span')
      meta.textContent = `${item.venue.name} | ${formatDateTime(item.start_at, {
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })}`

      const directions = document.createElement('a')
      directions.href = mapsUrl(item.venue.coordinates)
      directions.target = '_blank'
      directions.rel = 'noreferrer'
      directions.textContent = 'Open in maps'

      const inAppRoute = document.createElement('button')
      inAppRoute.type = 'button'
      inAppRoute.className = 'event-map-popup-route'
      inAppRoute.textContent = userCoords ? 'Show route on map' : 'Use location first'
      inAppRoute.disabled = !userCoords
      inAppRoute.addEventListener('click', (event) => {
        event.preventDefault()
        event.stopPropagation()
        drawSimpleRoute(item)
      })

      if (userCoords) {
        const routeHint = document.createElement('small')
        const miles = distanceMiles(userCoords, item.venue.coordinates)
        const walkingMinutes = Math.max(1, Math.round(miles * 20))
        routeHint.textContent = `Straight-line guide: ${formatDistance(miles)} | about ${walkingMinutes} min walk`
        popup.append(kicker, title, meta, routeHint, inAppRoute, directions)
        return popup
      }

      popup.append(kicker, title, meta, inAppRoute, directions)
      return popup
    }

    venues.forEach((venue) => {
      const venuePosition = L.latLng(venue.coordinates.lat, venue.coordinates.lng)
      L.marker(venuePosition, {
        icon: venueIcon(selectedVenueId === venue.id),
        title: venue.name,
      })
        .bindPopup(venuePopup(venue), {
          className: 'nightlife-leaflet-popup',
          closeButton: true,
          maxWidth: 260,
        })
        .on('click', () => {
          map.setView(venuePosition, Math.max(map.getZoom(), 17), { animate: true })
        })
        .addTo(layer)
    })

    events.forEach((item, index) => {
      const offset = (index % 5) * 0.000035
      const eventPosition = L.latLng(item.venue.coordinates.lat + offset, item.venue.coordinates.lng + offset)
      const marker = L.marker(eventPosition, {
        icon: eventIcon(selectedEventId === item.id),
        title: item.title,
        zIndexOffset: 500 + index,
      })
        .bindPopup(eventPopup(item), {
          className: 'nightlife-leaflet-popup',
          closeButton: true,
          maxWidth: 260,
        })
        .on('click', () => {
          map.setView(eventPosition, Math.max(map.getZoom(), 17), { animate: true })
        })
        .addTo(layer)

      if (selectedEventId === item.id) {
        map.setView(eventPosition, Math.max(map.getZoom(), 17), { animate: true })
        marker.openPopup()
      }
    })

    if (userCoords) {
      L.marker([userCoords.lat, userCoords.lng], {
        icon: L.divIcon({
          className: 'user-avatar-marker',
          html: '<span class="avatar-pulse"></span><span class="avatar-face"><span></span></span>',
          iconSize: [44, 44],
          iconAnchor: [22, 22],
        }),
        title: 'You are here',
        zIndexOffset: 1200,
      }).addTo(layer)
    }

    if (!hasFittedInitialMarkers.current && venues.length > 0) {
      const bounds = L.latLngBounds(venues.map((venue) => [venue.coordinates.lat, venue.coordinates.lng]))
      map.fitBounds(bounds.pad(0.18), { maxZoom: 17 })
      hasFittedInitialMarkers.current = true
    }
  }, [events, selectedEventId, selectedVenueId, userCoords, venues])

  useEffect(() => {
    const map = mapRef.current
    const routeLayer = routeLayerRef.current
    if (!map || !routeLayer) return

    routeLayer.clearLayers()
    if (!routeTarget || !userCoords) return

    const start = L.latLng(userCoords.lat, userCoords.lng)
    const destination = L.latLng(routeTarget.venue.coordinates.lat, routeTarget.venue.coordinates.lng)

    L.polyline([start, destination], {
      className: 'simple-route-line',
      color: '#32c3ff',
      weight: 5,
      opacity: 0.92,
      dashArray: '10 12',
      lineCap: 'round',
    }).addTo(routeLayer)

    L.circleMarker(start, {
      className: 'simple-route-start',
      radius: 8,
      color: '#fff9ef',
      fillColor: '#32c3ff',
      fillOpacity: 1,
      weight: 3,
    }).addTo(routeLayer)

    L.circleMarker(destination, {
      className: 'simple-route-finish',
      radius: 9,
      color: '#fff9ef',
      fillColor: '#ff7a29',
      fillOpacity: 1,
      weight: 3,
    }).addTo(routeLayer)

    map.fitBounds(L.latLngBounds([start, destination]).pad(0.25), { maxZoom: 17 })
  }, [routeTarget, userCoords])

  useEffect(() => {
    const area = areas.find((item) => item.slug === selectedArea)
    if (!area || !mapRef.current) return
    mapRef.current.setView([area.center.lat, area.center.lng], 16, { animate: true })
    setSelectedTown(area.name)
  }, [areas, selectedArea])

  async function searchIrelandTown(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const query = townQuery.trim()
    if (!query) return

    setTownSearchStatus('loading')
    setTownResults([])

    try {
      const response = await fetch(
        `https://nominatim.openstreetmap.org/search?format=jsonv2&countrycodes=ie&limit=8&addressdetails=1&q=${encodeURIComponent(
          query,
        )}`,
      )
      if (!response.ok) throw new Error('Town search failed')
      const results = (await response.json()) as TownSearchResult[]
      setTownResults(results)
      setTownSearchStatus(results.length ? 'idle' : 'empty')
    } catch {
      setTownSearchStatus('error')
    }
  }

  function chooseTown(result: TownSearchResult) {
    const lat = Number(result.lat)
    const lng = Number(result.lon)
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return

    mapRef.current?.setView([lat, lng], 16, { animate: true })
    setSelectedTown(result.display_name.split(',').slice(0, 3).join(', '))
    setTownResults([])
    setTownQuery('')
  }

  return (
    <div className="hero-panel district-panel">
      <div className="section-topline">
        <span>Live town map</span>
        <small>Zoom to building level, switch Irish towns, and use route buttons for in-app directions</small>
      </div>

      <div className="map-toolbar">
        <div>
          <span className="map-eyebrow">Viewing</span>
          <strong>{selectedTown}</strong>
        </div>
        <form className="map-search" onSubmit={searchIrelandTown}>
          <input
            type="search"
            value={townQuery}
            onChange={(event) => setTownQuery(event.target.value)}
            placeholder="Search any town in Ireland"
            aria-label="Search any town in Ireland"
          />
          <button type="submit">{townSearchStatus === 'loading' ? 'Searching...' : 'Go'}</button>
        </form>
      </div>

      {townResults.length ? (
        <div className="map-search-results">
          {townResults.map((result) => (
            <button key={result.place_id} type="button" onClick={() => chooseTown(result)}>
              {result.display_name}
            </button>
          ))}
        </div>
      ) : null}

      {townSearchStatus === 'empty' ? <p className="map-search-note">No Irish town matches found. Try a nearby place name.</p> : null}
      {townSearchStatus === 'error' ? <p className="map-search-note">Town search is unavailable right now. The map still works normally.</p> : null}

      {areas.length ? (
        <div className="map-area-strip">
          {areas.map((area, index) => (
            <button
              key={area.id}
              className={classNames(
                'map-area-pill',
                selectedArea === area.slug && 'active',
                `district-tone-${(index % 3) + 1}`,
              )}
              type="button"
              onClick={() => onSelectArea(selectedArea === area.slug ? '' : area.slug)}
            >
              {area.name}
            </button>
          ))}
        </div>
      ) : null}

      <div className="map-board real-map-board">
        <div ref={mapElementRef} className="leaflet-map" aria-label="Interactive town nightlife map" />
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
  const [routeTarget, setRouteTarget] = useState<EventWithDistance | null>(null)
  const { areas, venues, events } = useDiscoveryData(filters)

  const venueData = useMemo(() => venues.data ?? [], [venues.data])
  const eventData = useMemo(() => events.data ?? [], [events.data])
  const areaData = useMemo(() => areas.data ?? [], [areas.data])

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

  function showEventRouteInMap(event: EventWithDistance) {
    setRouteTarget(event)
    if (!location.coords) location.requestLocation()
    setSelectedEvent(null)
    setSelectedVenue(null)
  }

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
            <h1>Find pubs, bars, clubs, and events in one simple view.</h1>
            <p className="lede">
              Search by town, filter what matters, and check venues, hours, prices, and events without jumping around.
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
          userCoords={location.coords}
          routeTarget={routeTarget}
          onSelectArea={(slug) => setFilters((current) => ({ ...current, area: slug }))}
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
      <SidePanel
        selectedEvent={selectedEvent}
        selectedVenue={selectedVenue}
        hasLocation={Boolean(location.coords)}
        onClose={() => { setSelectedEvent(null); setSelectedVenue(null) }}
        onShowEventRoute={showEventRouteInMap}
      />
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
