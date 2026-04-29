import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {
  AppBar,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  CssBaseline,
  FormControl,
  FormControlLabel,
  IconButton,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  ThemeProvider,
  ToggleButton,
  ToggleButtonGroup,
  Toolbar,
  Typography,
  createTheme,
} from '@mui/material'
import AdminPanelSettingsRoundedIcon from '@mui/icons-material/AdminPanelSettingsRounded'
import DarkModeRoundedIcon from '@mui/icons-material/DarkModeRounded'
import ExploreRoundedIcon from '@mui/icons-material/ExploreRounded'
import LightModeRoundedIcon from '@mui/icons-material/LightModeRounded'
import LocationOnRoundedIcon from '@mui/icons-material/LocationOnRounded'
import MyLocationRoundedIcon from '@mui/icons-material/MyLocationRounded'
import NightlifeRoundedIcon from '@mui/icons-material/NightlifeRounded'
import PlaceRoundedIcon from '@mui/icons-material/PlaceRounded'
import ScheduleRoundedIcon from '@mui/icons-material/ScheduleRounded'
import TuneRoundedIcon from '@mui/icons-material/TuneRounded'

import { fetchRoute, initialConfig, useDiscoveryData, useEventDetail, useVenueDetail } from './api'
import { classNames, DAY_LABELS, distanceMiles, formatDateTime, formatDistance, mapsUrl } from './lib'
import type { Area, Coords, EventWithDistance, Filters, RouteResponse, Theme, VenueWithDistance } from './types'

type TownSearchResult = {
  place_id: number
  display_name: string
  lat: string
  lon: string
  boundingbox?: string[]
}

type RouteTarget = {
  coordinates: Coords
  label: string
  detail: string
  distanceMiles?: number | null
}

type RouteState = {
  loading: boolean
  error: string | null
  walkingRoute: RouteResponse | null
  drivingRoute: RouteResponse | null
  drivingUnavailable: boolean
  targetLabel: string | null
}

const DEFAULT_TOWN = {
  label: 'Ballina, Co. Mayo',
  coords: { lat: 54.1159, lng: -9.1536 },
}

function formatTravelMinutes(seconds: number) {
  return `${Math.max(1, Math.round(seconds / 60))} min`
}

const EVENT_MARKER_SVG = `
  <svg class="event-marker-svg" viewBox="0 0 64 78" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="eventPinGlow" x1="10%" x2="90%" y1="0%" y2="100%">
        <stop offset="0%" stop-color="#ec4899" />
        <stop offset="54%" stop-color="#8b5cf6" />
        <stop offset="100%" stop-color="#2563eb" />
      </linearGradient>
      <linearGradient id="eventSparkGlow" x1="0%" x2="100%" y1="0%" y2="100%">
        <stop offset="0%" stop-color="#fff4fb" />
        <stop offset="100%" stop-color="#fefce8" />
      </linearGradient>
    </defs>
    <path class="event-pin-shadow" d="M32 76C22 60 8 50 8 28C8 12 18 3 32 3s24 9 24 25c0 22-14 32-24 48Z" />
    <path class="event-pin-body" d="M32 72C22 56 10 48 10 28C10 13 19 5 32 5s22 8 22 23c0 20-12 28-22 44Z" />
    <circle class="event-pin-inner" cx="32" cy="29" r="15" />
    <path class="event-pin-star" d="m32 15.8 2.8 5.7 6.3.9-4.6 4.5 1.1 6.3-5.6-2.9-5.6 2.9 1.1-6.3-4.6-4.5 6.3-.9 2.8-5.7Z" />
    <path class="event-pin-ticket" d="M24 35.5h16c.8 0 1.5.7 1.5 1.5v2.2c-1.1.2-1.9 1.1-1.9 2.3s.8 2.1 1.9 2.3V46c0 .8-.7 1.5-1.5 1.5H24c-.8 0-1.5-.7-1.5-1.5v-2.2c1.1-.2 1.9-1.1 1.9-2.3s-.8-2.1-1.9-2.3V37c0-.8.7-1.5 1.5-1.5Zm6 2.3v7.4m4-7.4v7.4" />
  </svg>
`

const PUB_MARKER_SVG = `
  <svg class="pub-marker-svg" viewBox="0 0 64 78" aria-hidden="true" focusable="false">
    <defs>
      <linearGradient id="pubPinGlow" x1="12%" x2="88%" y1="0%" y2="100%">
        <stop offset="0%" stop-color="#14b8a6" />
        <stop offset="56%" stop-color="#0f766e" />
        <stop offset="100%" stop-color="#2563eb" />
      </linearGradient>
    </defs>
    <path class="pub-pin-shadow" d="M32 76C22 60 8 50 8 28C8 12 18 3 32 3s24 9 24 25c0 22-14 32-24 48Z" />
    <path class="pub-pin-body" d="M32 72C22 56 10 48 10 28C10 13 19 5 32 5s22 8 22 23c0 20-12 28-22 44Z" />
    <circle class="pub-pin-inner" cx="32" cy="29" r="15" />
    <path class="pub-pin-glass" d="M23 19h16v5c0 3-1.8 5.8-4.7 7.2V37h4.2a2 2 0 1 1 0 4H25.5a2 2 0 1 1 0-4h4.8v-5.8A8.1 8.1 0 0 1 23 24v-5Zm3.8 5c0 2.9 2.3 5.2 5.2 5.2s5.2-2.3 5.2-5.2v-1.2H26.8V24Z" />
  </svg>
`

function UiThemeProvider({ mode, children }: { mode: Theme; children: ReactNode }) {
  const muiTheme = useMemo(
    () =>
      createTheme({
        palette: {
          mode,
          primary: { main: mode === 'dark' ? '#7dd3fc' : '#0f766e' },
          secondary: { main: mode === 'dark' ? '#c084fc' : '#2563eb' },
          background: {
            default: mode === 'dark' ? '#070b14' : '#f7fafc',
            paper: mode === 'dark' ? '#111827' : '#ffffff',
          },
          text: {
            primary: mode === 'dark' ? '#f8fafc' : '#17202a',
            secondary: mode === 'dark' ? '#a9b7ca' : '#5c6b7a',
          },
        },
        shape: { borderRadius: 8 },
        typography: {
          fontFamily: '"Aptos", "Segoe UI", sans-serif',
          h1: { fontWeight: 800, letterSpacing: 0 },
          h2: { fontWeight: 800, letterSpacing: 0 },
          h3: { fontWeight: 750, letterSpacing: 0 },
          button: { fontWeight: 750, textTransform: 'none' },
        },
        components: {
          MuiCard: {
            styleOverrides: {
              root: {
                border: mode === 'dark' ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(23,111,143,0.12)',
                boxShadow: mode === 'dark' ? '0 18px 42px rgba(0,0,0,0.24)' : '0 16px 34px rgba(34,71,82,0.08)',
              },
            },
          },
          MuiPaper: {
            styleOverrides: {
              root: {
                backgroundImage: 'none',
              },
            },
          },
        },
      }),
    [mode],
  )

  return (
    <ThemeProvider theme={muiTheme}>
      <CssBaseline enableColorScheme />
      {children}
    </ThemeProvider>
  )
}

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
    <AppBar className="mui-app-header" color="transparent" elevation={0} position="static">
      <Toolbar disableGutters sx={{ gap: 2, justifyContent: 'space-between', py: 2 }}>
        <Stack component="a" direction="row" href="/" sx={{ alignItems: 'center', color: 'text.primary', gap: 1.5, textDecoration: 'none' }}>
          <Box className="brand-badge mui-brand-badge">
            <NightlifeRoundedIcon fontSize="small" />
          </Box>
          <Box>
            <Typography sx={{ fontWeight: 850, lineHeight: 1.1 }}>Town Nightlife Finder</Typography>
            <Typography color="text.secondary" sx={{ fontSize: '0.82rem' }}>Map, filter, and plan the night</Typography>
          </Box>
        </Stack>
        <Stack direction="row" sx={{ alignItems: 'center', flexWrap: 'wrap', gap: 1, justifyContent: 'flex-end' }}>
          <Button color="inherit" href="/" startIcon={<ExploreRoundedIcon />} variant="text">
            Explore
          </Button>
          <Button color="inherit" href="/login" startIcon={<AdminPanelSettingsRoundedIcon />} variant="outlined">
            Admin
          </Button>
          <Button
            color={hasLocation ? 'success' : 'primary'}
            onClick={onUseLocation}
            startIcon={hasLocation ? <LocationOnRoundedIcon /> : <MyLocationRoundedIcon />}
            variant={hasLocation ? 'contained' : 'outlined'}
          >
            {hasLocation ? 'Location on' : 'Use location'}
          </Button>
          <IconButton aria-label="Toggle theme" color="inherit" onClick={onToggleTheme}>
            {theme === 'dark' ? <LightModeRoundedIcon /> : <DarkModeRoundedIcon />}
          </IconButton>
        </Stack>
      </Toolbar>
    </AppBar>
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
  onShowRoute,
}: {
  selectedEvent: EventWithDistance | null
  selectedVenue: VenueWithDistance | null
  hasLocation: boolean
  onClose: () => void
  onShowRoute: (target: RouteTarget) => void
}) {
  if (!selectedEvent && !selectedVenue) return null

  const title = selectedEvent ? selectedEvent.title : selectedVenue!.name
  const distance = selectedEvent?.distanceMiles ?? selectedVenue?.distanceMiles ?? null
  const destination = selectedEvent?.venue.coordinates ?? selectedVenue?.coordinates

  return (
    <>
      <button className="panel-scrim" type="button" onClick={onClose} aria-label="Close panel" />
      <aside className="side-panel" role="dialog" aria-modal="true" aria-labelledby="side-panel-title">
        <button className="side-panel-close" type="button" onClick={onClose}>
          x
        </button>
        <div className="side-panel-ribbon" />
        <p className="side-panel-kicker">
          {selectedEvent
            ? `${selectedEvent.genre} event`
            : `${selectedVenue?.type} in ${selectedVenue?.area.name}`}
        </p>
        <h2 id="side-panel-title">{title}</h2>
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
            <button
              className="inline-route side-route-button"
              type="button"
              onClick={() =>
                onShowRoute(
                  selectedEvent
                    ? {
                        coordinates: selectedEvent.venue.coordinates,
                        label: selectedEvent.title,
                        detail: selectedEvent.venue.name,
                        distanceMiles: selectedEvent.distanceMiles,
                      }
                    : {
                        coordinates: selectedVenue!.coordinates,
                        label: selectedVenue!.name,
                        detail: selectedVenue!.address,
                        distanceMiles: selectedVenue!.distanceMiles,
                      },
                )
              }
            >
              {hasLocation ? 'Show route in app' : 'Use location for route'}
            </button>
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
  onRequestRoute,
  onSelectArea,
}: {
  areas: Area[]
  venues: VenueWithDistance[]
  events: EventWithDistance[]
  selectedArea: string
  selectedEventId: number | null
  selectedVenueId: number | null
  userCoords: Coords | null
  routeTarget: RouteTarget | null
  onRequestRoute: (target: RouteTarget) => void
  onSelectArea: (slug: string) => void
}) {
  const mapElementRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markerLayerRef = useRef<L.LayerGroup | null>(null)
  const routeLayerRef = useRef<L.LayerGroup | null>(null)
  const hasFittedInitialMarkers = useRef(false)
  const [mapViewMode, setMapViewMode] = useState<'all' | 'pubs' | 'events'>('all')
  const [routeState, setRouteState] = useState<RouteState>({
    loading: false,
    error: null,
    walkingRoute: null,
    drivingRoute: null,
    drivingUnavailable: false,
    targetLabel: null,
  })
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
        html: `<span class="marker-glow"></span>${PUB_MARKER_SVG}`,
        iconSize: [48, 58],
        iconAnchor: [24, 54],
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

      const inAppRoute = document.createElement('button')
      inAppRoute.type = 'button'
      inAppRoute.className = 'event-map-popup-route'
      inAppRoute.textContent = userCoords ? 'Show route on map' : 'Use location first'
      inAppRoute.disabled = !userCoords
      inAppRoute.addEventListener('click', (event) => {
        event.preventDefault()
        event.stopPropagation()
        onRequestRoute({
          coordinates: venue.coordinates,
          label: venue.name,
          detail: venue.address,
          distanceMiles: venue.distanceMiles,
        })
      })

      const directions = document.createElement('a')
      directions.href = mapsUrl(venue.coordinates)
      directions.target = '_blank'
      directions.rel = 'noreferrer'
      directions.textContent = 'Open in maps'

      if (userCoords) {
        const routeHint = document.createElement('small')
        routeHint.textContent = 'Show route on map for walking directions that follow roads.'
        popup.append(kicker, title, meta, routeHint, inAppRoute, directions)
        return popup
      }

      popup.append(kicker, title, meta, inAppRoute, directions)
      return popup
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
        onRequestRoute({
          coordinates: item.venue.coordinates,
          label: item.title,
          detail: item.venue.name,
          distanceMiles: item.distanceMiles,
        })
      })

      if (userCoords) {
        const routeHint = document.createElement('small')
        routeHint.textContent = 'Show route on map for walking directions that follow roads.'
        popup.append(kicker, title, meta, routeHint, inAppRoute, directions)
        return popup
      }

      popup.append(kicker, title, meta, inAppRoute, directions)
      return popup
    }

    const visiblePositions: L.LatLng[] = []

    if (mapViewMode !== 'events') {
      venues.forEach((venue) => {
        const venuePosition = L.latLng(venue.coordinates.lat, venue.coordinates.lng)
        visiblePositions.push(venuePosition)
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
    }

    if (mapViewMode !== 'pubs') {
      events.forEach((item, index) => {
        const offset = (index % 5) * 0.000035
        const eventPosition = L.latLng(item.venue.coordinates.lat + offset, item.venue.coordinates.lng + offset)
        visiblePositions.push(eventPosition)
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
    }

    if (userCoords) {
      L.marker([userCoords.lat, userCoords.lng], {
        icon: L.divIcon({
          className: 'user-avatar-marker',
          html:
            '<span class="avatar-pulse"></span><span class="avatar-marker-pin"><span class="avatar-marker-badge"><span class="avatar-head"></span><span class="avatar-body"></span></span></span>',
          iconSize: [42, 56],
          iconAnchor: [21, 52],
        }),
        title: 'You are here',
        zIndexOffset: 1200,
      }).addTo(layer)
    }

    if (!hasFittedInitialMarkers.current && visiblePositions.length > 0) {
      const bounds = L.latLngBounds(visiblePositions)
      map.fitBounds(bounds.pad(0.18), { maxZoom: 17 })
      hasFittedInitialMarkers.current = true
    }
  }, [events, mapViewMode, onRequestRoute, selectedEventId, selectedVenueId, userCoords, venues])

  useEffect(() => {
    const map = mapRef.current
    const routeLayer = routeLayerRef.current
    if (!map || !routeLayer) return
    let active = true
    routeLayer.clearLayers()
    if (!routeTarget || !userCoords) {
      setRouteState({ loading: false, error: null, walkingRoute: null, drivingRoute: null, drivingUnavailable: false, targetLabel: null })
      return () => {
        active = false
      }
    }

    const start = L.latLng(userCoords.lat, userCoords.lng)
    const destination = L.latLng(routeTarget.coordinates.lat, routeTarget.coordinates.lng)
    setRouteState({ loading: true, error: null, walkingRoute: null, drivingRoute: null, drivingUnavailable: false, targetLabel: routeTarget.label })

    Promise.allSettled([
      fetchRoute(userCoords, routeTarget.coordinates, 'walking'),
      fetchRoute(userCoords, routeTarget.coordinates, 'driving'),
    ])
      .then(([walkingResult, drivingResult]) => {
        if (!active) return
        if (walkingResult.status !== 'fulfilled') {
          throw walkingResult.reason instanceof Error ? walkingResult.reason : new Error('Could not load walking directions right now.')
        }

        const walkingRoute = walkingResult.value
        const rawDrivingRoute = drivingResult.status === 'fulfilled' ? drivingResult.value : null
        const drivingLooksDuplicated =
          rawDrivingRoute !== null &&
          Math.abs(rawDrivingRoute.duration_seconds - walkingRoute.duration_seconds) < 1 &&
          Math.abs(rawDrivingRoute.distance_meters - walkingRoute.distance_meters) < 1
        const drivingRoute = drivingLooksDuplicated ? null : rawDrivingRoute
        const routePoints = walkingRoute.geometry.map((point) => L.latLng(point.lat, point.lng))
        if (!routePoints.length) throw new Error('No route geometry returned.')

        L.polyline(routePoints, {
          className: 'osrm-route-line',
          color: '#32c3ff',
          weight: 6,
          opacity: 0.96,
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

        map.fitBounds(L.latLngBounds(routePoints).pad(0.18), { maxZoom: 17 })
        setRouteState({
          loading: false,
          error: null,
          walkingRoute,
          drivingRoute,
          drivingUnavailable: drivingResult.status !== 'fulfilled' || drivingLooksDuplicated,
          targetLabel: routeTarget.label,
        })
      })
      .catch((error: Error) => {
        if (!active) return
        routeLayer.clearLayers()
        setRouteState({
          loading: false,
          error: error.message || 'Could not load directions right now.',
          walkingRoute: null,
          drivingRoute: null,
          drivingUnavailable: false,
          targetLabel: routeTarget.label,
        })
      })

    return () => {
      active = false
    }
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

      <div className="map-view-toolbar">
        <ToggleButtonGroup
          exclusive
          size="small"
          value={mapViewMode}
          onChange={(_, value: 'all' | 'pubs' | 'events' | null) => {
            if (!value) return
            setMapViewMode(value)
          }}
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="pubs">Pubs</ToggleButton>
          <ToggleButton value="events">Events</ToggleButton>
        </ToggleButtonGroup>
        <div className="map-legend">
          <span className="map-legend-item"><span className="map-legend-dot pub-dot" />Pubs</span>
          <span className="map-legend-item"><span className="map-legend-dot event-dot" />Events</span>
        </div>
      </div>

      {routeState.loading ? <p className="map-route-note">Finding walking route to {routeState.targetLabel}...</p> : null}
      {routeState.error ? <p className="map-route-note route-error">{routeState.error}</p> : null}
      {routeState.walkingRoute && !routeState.loading ? (
        <p className="map-route-note">
          Walking route to {routeState.targetLabel}: {(routeState.walkingRoute.distance_meters / 1000).toFixed(1)} km | walking{' '}
          {formatTravelMinutes(routeState.walkingRoute.duration_seconds)}
          {routeState.drivingRoute ? ` | driving ${formatTravelMinutes(routeState.drivingRoute.duration_seconds)}` : ''}
          {routeState.drivingUnavailable ? ' | driving estimate unavailable' : ''}
        </p>
      ) : null}

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

function MetricTile({ value, label }: { value: number | string; label: string }) {
  return (
    <Paper className="mui-metric-tile" variant="outlined">
      <Typography component="strong" variant="h5">{value}</Typography>
      <Typography color="text.secondary" variant="body2">{label}</Typography>
    </Paper>
  )
}

function FilterSurface({
  filters,
  genres,
  venueTypes,
  priceBands,
  onChange,
}: {
  filters: Filters
  genres: string[]
  venueTypes: string[]
  priceBands: string[]
  onChange: (filters: Filters) => void
}) {
  return (
    <Paper className="mui-filter-surface" component="section" elevation={0} variant="outlined">
      <Stack direction={{ md: 'row', xs: 'column' }} sx={{ alignItems: { md: 'center', xs: 'stretch' }, gap: 2, justifyContent: 'space-between', mb: 2 }}>
        <Stack direction="row" sx={{ alignItems: 'center', gap: 1.2 }}>
          <TuneRoundedIcon color="primary" />
          <Box>
            <Typography sx={{ fontWeight: 800 }}>Filter the night</Typography>
            <Typography color="text.secondary" variant="body2">Sort by vibe, spend, timing, or what is near you</Typography>
          </Box>
        </Stack>
        <FormControlLabel
          control={<Switch checked={filters.open_now} onChange={() => onChange({ ...filters, open_now: !filters.open_now })} />}
          label="Open now"
        />
      </Stack>
      <Box className="mui-filter-grid">
        <TextField
          label="Date"
          onChange={(event) => onChange({ ...filters, date: event.target.value })}
          slotProps={{ inputLabel: { shrink: true } }}
          type="date"
          value={filters.date}
        />
        <FormControl>
          <InputLabel>Genre</InputLabel>
          <Select label="Genre" value={filters.genre} onChange={(event) => onChange({ ...filters, genre: event.target.value })}>
            <MenuItem value="">Any genre</MenuItem>
            {genres.map((genre) => <MenuItem key={genre} value={genre}>{genre}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl>
          <InputLabel>Venue type</InputLabel>
          <Select label="Venue type" value={filters.venue_type} onChange={(event) => onChange({ ...filters, venue_type: event.target.value })}>
            <MenuItem value="">Any venue</MenuItem>
            {venueTypes.map((type) => <MenuItem key={type} value={type}>{type}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl>
          <InputLabel>Price band</InputLabel>
          <Select label="Price band" value={filters.price_band} onChange={(event) => onChange({ ...filters, price_band: event.target.value })}>
            <MenuItem value="">Any budget</MenuItem>
            {priceBands.map((band) => <MenuItem key={band} value={band}>{band}</MenuItem>)}
          </Select>
        </FormControl>
        <FormControl>
          <InputLabel>Sort by</InputLabel>
          <Select label="Sort by" value={filters.sort} onChange={(event) => onChange({ ...filters, sort: event.target.value })}>
            <MenuItem value="time">Next event / opening time</MenuItem>
            <MenuItem value="name">Venue name</MenuItem>
            <MenuItem value="price">Price</MenuItem>
            <MenuItem value="area">Area</MenuItem>
          </Select>
        </FormControl>
      </Box>
    </Paper>
  )
}

function VenueCard({ venue, onOpen }: { venue: VenueWithDistance; onOpen: () => void }) {
  return (
    <Card className="mui-list-card venue-list-card" variant="outlined">
      <CardActionArea onClick={onOpen}>
        <CardContent>
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1, mb: 1 }}>
            <Chip className="card-chip card-chip-solid" color="primary" label={venue.type} size="small" />
            <Chip className="card-chip" label={venue.area.name} size="small" variant="outlined" />
            <Chip className="card-chip" label={venue.price_band} size="small" variant="outlined" />
          </Stack>
          <Typography gutterBottom variant="h6">{venue.name}</Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }} variant="body2">{venue.description}</Typography>
          <Box className="mui-card-facts">
            <span><ScheduleRoundedIcon />{venue.opens_at} - {venue.closes_at}</span>
            <span><PlaceRoundedIcon />{venue.address}</span>
            <span><NightlifeRoundedIcon />{formatDateTime(venue.next_event_start)}</span>
            <span><MyLocationRoundedIcon />{formatDistance(venue.distanceMiles)}</span>
          </Box>
        </CardContent>
      </CardActionArea>
    </Card>
  )
}

function EventCard({ item, onOpen }: { item: EventWithDistance; onOpen: () => void }) {
  return (
    <Card className="mui-list-card event-card" variant="outlined">
      <CardActionArea onClick={onOpen}>
        <CardContent>
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1, mb: 1 }}>
            <Chip className="card-chip card-chip-solid" color="secondary" label={item.genre} size="small" />
            <Chip className="card-chip" label={item.venue.name} size="small" variant="outlined" />
            <Chip className="card-chip" label={item.price_label} size="small" variant="outlined" />
          </Stack>
          <Typography gutterBottom variant="h6">{item.title}</Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }} variant="body2">{item.description}</Typography>
          <Box className="mui-card-facts">
            <span><ScheduleRoundedIcon />{formatDateTime(item.start_at)}</span>
            <span><NightlifeRoundedIcon />{item.venue.opens_at} - {item.venue.closes_at}</span>
            <span><PlaceRoundedIcon />{item.venue.area.name}</span>
            <span><MyLocationRoundedIcon />{formatDistance(item.distanceMiles)}</span>
          </Box>
        </CardContent>
      </CardActionArea>
    </Card>
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
  const [routeTarget, setRouteTarget] = useState<RouteTarget | null>(null)
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
  const panelOpen = Boolean(selectedEvent || selectedVenue)

  function showRouteInMap(target: RouteTarget) {
    setRouteTarget(target)
    if (!location.coords) location.requestLocation()
    setSelectedEvent(null)
    setSelectedVenue(null)
  }

  return (
    <UiThemeProvider mode={theme}>
      <div className={`nightlife-app${panelOpen ? ' panel-open' : ''}`}>
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
              <Box className="mui-hero-metrics">
                <MetricTile label="venues matching" value={venuesWithDistance.length} />
                <MetricTile label="events scheduled" value={allEventsWithDistance.length} />
                <MetricTile label="nearby picks" value={location.coords ? nearbyEvents.length : 0} />
              </Box>
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
            onRequestRoute={showRouteInMap}
            onSelectArea={(slug) => setFilters((current) => ({ ...current, area: slug }))}
          />
        </section>
        <FilterSurface filters={filters} genres={genres} priceBands={priceBands} venueTypes={venueTypes} onChange={setFilters} />
        {areas.error || venues.error || events.error ? (
          <section className="filter-surface">
            <p className="error-note">Data load issue: {[areas.error, venues.error, events.error].filter(Boolean).join(' | ')}</p>
          </section>
        ) : null}
        <Paper className="mui-events-toolbar" component="section" elevation={0} variant="outlined">
          <ToggleButtonGroup
            exclusive
            onChange={(_, value: 'all' | 'nearby' | null) => {
              if (!value) return
              setActiveTab(value)
              if (value === 'nearby' && !location.coords) location.requestLocation()
            }}
            value={activeTab}
          >
            <ToggleButton value="all">All events</ToggleButton>
            <ToggleButton value="nearby">Events close by</ToggleButton>
          </ToggleButtonGroup>
          <Typography color="text.secondary" variant="body2">
            {location.coords ? 'Nearby results use your current location.' : location.error ?? 'Enable location to show exact distance from you.'}
          </Typography>
        </Paper>
        <section className="listing-grid">
          <div className="listing-column listing-column-venues">
            <div className="section-headline section-headline-venues">
              <div className="section-title-row">
                <div>
                  <p className="section-kicker">Places</p>
                  <h2>Bars and venues</h2>
                </div>
                <span className="section-count">{venuesWithDistance.length}</span>
              </div>
              <p>Browse the places first, then open any venue for hours, pricing, and details.</p>
            </div>
            {venues.loading ? <p className="empty-message">Loading venues...</p> : null}
            {!venues.loading && !venueData.length ? <p className="empty-message">No venues match the current filters.</p> : null}
            <div className="card-stack">
              {venuesWithDistance.map((venue) => (
                <VenueCard key={venue.id} venue={venue} onOpen={() => { setSelectedVenue(venue); setSelectedEvent(null) }} />
              ))}
            </div>
          </div>
          <div className="listing-column listing-column-events">
            <div className="section-headline section-headline-events">
              <div className="section-title-row">
                <div>
                  <p className="section-kicker">What's on</p>
                  <h2>{activeTab === 'nearby' ? 'Events close by' : 'Upcoming events'}</h2>
                </div>
                <span className="section-count">{displayedEvents.length}</span>
              </div>
              <p>See tonight's sessions, gigs, karaoke, and club nights separately from the venue list.</p>
            </div>
            {events.loading ? <p className="empty-message">Loading events...</p> : null}
            {!events.loading && !displayedEvents.length ? <p className="empty-message">No events match the current filters.</p> : null}
            <div className="card-stack">
              {displayedEvents.map((item) => (
                <EventCard key={item.id} item={item} onOpen={() => { setSelectedEvent(item); setSelectedVenue(null) }} />
              ))}
            </div>
          </div>
        </section>
        <SidePanel
          selectedEvent={selectedEvent}
          selectedVenue={selectedVenue}
          hasLocation={Boolean(location.coords)}
          onClose={() => { setSelectedEvent(null); setSelectedVenue(null) }}
          onShowRoute={showRouteInMap}
        />
      </div>
    </UiThemeProvider>
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
    <UiThemeProvider mode={theme}>
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
    </UiThemeProvider>
  )
}

function EventPage({ eventId }: { eventId: number }) {
  const { theme, toggleTheme } = useTheme()
  const location = useCurrentLocation()
  const { data, loading, error } = useEventDetail(eventId)

  return (
    <UiThemeProvider mode={theme}>
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
    </UiThemeProvider>
  )
}

export default function App() {
  if (initialConfig.page === 'venue' && initialConfig.venueSlug) return <VenuePage slug={initialConfig.venueSlug} />
  if (initialConfig.page === 'event' && initialConfig.eventId) return <EventPage eventId={initialConfig.eventId} />
  return <HomePage />
}
