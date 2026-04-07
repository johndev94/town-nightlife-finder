declare const React: any;
declare const ReactDOM: any;

const { useEffect, useMemo, useState } = React;

type Area = {
  id: number;
  name: string;
  slug: string;
  description: string;
  center: { lat: number; lng: number };
  bounds: { north: number; south: number; east: number; west: number };
};

type Coords = { lat: number; lng: number };
type Theme = "dark" | "light";

type Venue = {
  id: number;
  name: string;
  slug: string;
  type: string;
  address: string;
  description: string;
  price_band: string;
  area: { name: string; slug: string };
  opens_at: string;
  closes_at: string;
  coordinates: Coords;
  source: {
    type: string;
    url: string | null;
    status: string;
    confidence: number;
    last_verified_at: string;
  };
  socials: {
    facebook?: string | null;
    instagram?: string | null;
    website?: string | null;
  };
  next_event_start: string | null;
  upcoming_event_count: number;
};

type EventItem = {
  id: number;
  title: string;
  description: string;
  genre: string;
  start_at: string;
  end_at: string;
  price_label: string;
  price_amount: number | null;
  venue: {
    name: string;
    slug: string;
    type: string;
    address: string;
    price_band: string;
    opens_at: string;
    closes_at: string;
    coordinates: Coords;
    area: { name: string; slug: string };
  };
  source: {
    type: string;
    url: string | null;
    status: string;
    confidence: number;
    last_verified_at: string;
  };
};

type VenueDetail = Venue & {
  opening_hours: Array<{ day_of_week: number; open_time: string; close_time: string; is_overnight: number }>;
  events: EventItem[];
};

type AppConfig = { page: "home" | "venue" | "event"; venueSlug: string | null; eventId?: number | null };
type Filters = {
  area: string;
  genre: string;
  venue_type: string;
  price_band: string;
  date: string;
  sort: string;
  open_now: boolean;
};

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const initialConfig = (window as any).__APP_CONFIG__ as AppConfig;

function formatDateTime(value: string | null, options?: Intl.DateTimeFormatOptions) {
  if (!value) return "TBC";
  return new Intl.DateTimeFormat(
    "en-GB",
    options ?? { weekday: "short", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" }
  ).format(new Date(value));
}

function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(" ");
}

function mapsUrl(destination: Coords) {
  return `https://www.google.com/maps/dir/?api=1&destination=${destination.lat},${destination.lng}&travelmode=walking`;
}

function distanceMiles(from: Coords, to: Coords) {
  const toRadians = (value: number) => (value * Math.PI) / 180;
  const earthRadiusMiles = 3958.8;
  const latDelta = toRadians(to.lat - from.lat);
  const lngDelta = toRadians(to.lng - from.lng);
  const a =
    Math.sin(latDelta / 2) ** 2 +
    Math.cos(toRadians(from.lat)) * Math.cos(toRadians(to.lat)) * Math.sin(lngDelta / 2) ** 2;
  return 2 * earthRadiusMiles * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function formatDistance(distance: number | null | undefined) {
  if (distance === null || distance === undefined) return "Use location";
  if (distance < 0.15) return `${Math.round(distance * 5280)} ft away`;
  return `${distance.toFixed(1)} miles away`;
}

function useFetch<T>(url: string, deps: any[]) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetch(url)
      .then((response) => {
        if (!response.ok) throw new Error(`Request failed: ${response.status}`);
        return response.json();
      })
      .then((json) => {
        if (active) setData(json);
      })
      .catch((err) => {
        if (active) setError(err.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, deps);

  return { data, loading, error };
}

function useCurrentLocation() {
  const [coords, setCoords] = useState<Coords | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  function requestLocation() {
    if (!navigator.geolocation) {
      setState("error");
      setError("Geolocation is not available in this browser.");
      return;
    }
    setState("loading");
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setCoords({ lat: position.coords.latitude, lng: position.coords.longitude });
        setState("ready");
      },
      () => {
        setState("error");
        setError("Location permission was blocked.");
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }

  return { coords, state, error, requestLocation };
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => {
    const saved = window.localStorage.getItem("tnf-theme");
    return saved === "light" || saved === "dark" ? saved : "dark";
  });

  useEffect(() => {
    document.body.setAttribute("data-theme", theme);
    window.localStorage.setItem("tnf-theme", theme);
  }, [theme]);

  return {
    theme,
    toggleTheme: () => setTheme((current) => (current === "dark" ? "light" : "dark")),
  };
}

function useDiscoveryData(filters: Filters) {
  const query = useMemo(() => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (typeof value === "boolean") {
        if (value) params.set(key, "1");
      } else if (value) {
        params.set(key, value);
      }
    });
    return params.toString();
  }, [filters]);

  return {
    areas: useFetch<Area[]>("/api/areas", []),
    venues: useFetch<Venue[]>(`/api/venues?${query}`, [query]),
    events: useFetch<EventItem[]>(`/api/events?${query}`, [query]),
  };
}

function Header({
  theme,
  onToggleTheme,
  onUseLocation,
  hasLocation,
}: {
  theme: Theme;
  onToggleTheme: () => void;
  onUseLocation: () => void;
  hasLocation: boolean;
}) {
  return (
    <header className="app-header">
      <a className="app-brand" href="/">
        <span className="brand-badge">TN</span>
        <span>
          <strong>Town Nightlife Finder</strong>
          <small>Map it, sort it, and get there fast</small>
        </span>
      </a>
      <nav className="app-nav">
        <a href="/">Explore town</a>
        <a href="/login">Admin / Owner</a>
        <button className="theme-toggle" type="button" onClick={onUseLocation}>
          {hasLocation ? "Location on" : "Use location"}
        </button>
        <button className="theme-toggle" type="button" onClick={onToggleTheme}>
          {theme === "dark" ? "Bright mode" : "Dark mode"}
        </button>
      </nav>
    </header>
  );
}

function MapPanel({
  areas,
  venues,
  selectedArea,
  onSelectArea,
}: {
  areas: Area[];
  venues: Venue[];
  selectedArea: string;
  onSelectArea: (slug: string) => void;
}) {
  if (!areas.length) return null;
  const north = Math.max(...areas.map((area) => area.bounds.north));
  const south = Math.min(...areas.map((area) => area.bounds.south));
  const east = Math.max(...areas.map((area) => area.bounds.east));
  const west = Math.min(...areas.map((area) => area.bounds.west));

  return (
    <div className="hero-panel district-panel">
      <div className="section-topline">
        <span>Town map</span>
        <small>Tap an area or pin to filter the listings</small>
      </div>
      <div className="map-board">
        {areas.map((area, index) => {
          const left = ((area.center.lng - west) / (east - west)) * 100;
          const top = 100 - ((area.center.lat - south) / (north - south)) * 100;
          return (
            <button
              key={area.id}
              className={classNames("map-area-chip", selectedArea === area.slug && "active", `district-tone-${(index % 3) + 1}`)}
              style={{ left: `${left}%`, top: `${top}%` }}
              onClick={() => onSelectArea(selectedArea === area.slug ? "" : area.slug)}
            >
              {area.name}
            </button>
          );
        })}
        {venues.map((venue) => {
          const left = ((venue.coordinates.lng - west) / (east - west)) * 100;
          const top = 100 - ((venue.coordinates.lat - south) / (north - south)) * 100;
          return (
            <a key={venue.id} href={`/venues/${venue.slug}`} className="map-pin" style={{ left: `${left}%`, top: `${top}%` }}>
              <span>{venue.name}</span>
            </a>
          );
        })}
      </div>
    </div>
  );
}

function HomePage() {
  const { theme, toggleTheme } = useTheme();
  const location = useCurrentLocation();
  const [filters, setFilters] = useState<Filters>({
    area: "",
    genre: "",
    venue_type: "",
    price_band: "",
    date: new Date().toISOString().slice(0, 10),
    sort: "time",
    open_now: false,
  });
  const [activeTab, setActiveTab] = useState<"all" | "nearby">("all");
  const { areas, venues, events } = useDiscoveryData(filters);

  const genres = useMemo(() => Array.from(new Set((events.data ?? []).map((event) => event.genre))).sort(), [events.data]);
  const venueTypes = useMemo(() => Array.from(new Set((venues.data ?? []).map((venue) => venue.type))).sort(), [venues.data]);
  const priceBands = useMemo(() => Array.from(new Set((venues.data ?? []).map((venue) => venue.price_band))).sort(), [venues.data]);

  const venuesWithDistance = useMemo(
    () =>
      (venues.data ?? []).map((venue) => ({
        ...venue,
        distanceMiles: location.coords ? distanceMiles(location.coords, venue.coordinates) : null,
      })),
    [venues.data, location.coords]
  );

  const allEventsWithDistance = useMemo(
    () =>
      (events.data ?? []).map((event) => ({
        ...event,
        distanceMiles: location.coords ? distanceMiles(location.coords, event.venue.coordinates) : null,
      })),
    [events.data, location.coords]
  );

  const nearbyEvents = useMemo(
    () =>
      allEventsWithDistance
        .filter((event) => event.distanceMiles !== null)
        .sort((left, right) => (left.distanceMiles ?? 9999) - (right.distanceMiles ?? 9999))
        .slice(0, 8),
    [allEventsWithDistance]
  );

  const displayedEvents = activeTab === "nearby" ? nearbyEvents : allEventsWithDistance;
  const spotlight = venuesWithDistance[0] ?? null;

  return (
    <div className="nightlife-app">
      <Header theme={theme} onToggleTheme={toggleTheme} onUseLocation={location.requestLocation} hasLocation={Boolean(location.coords)} />
      <section className="hero-shell">
        <div className="hero-panel hero-copy">
          <p className="kicker">Town nightlife planner</p>
          <h1>Map the town. Find events close by. Get directions in one tap.</h1>
          <p className="lede">Explore nightlife by district, switch to nearby events using your current location, and see exactly how far each pub, bar, and event is from you.</p>
          <div className="hero-metrics">
            <div><strong>{venuesWithDistance.length}</strong><span>venues matching now</span></div>
            <div><strong>{allEventsWithDistance.length}</strong><span>events in the schedule</span></div>
            <div><strong>{location.coords ? nearbyEvents.length : 0}</strong><span>nearby picks ready</span></div>
          </div>
          {spotlight ? (
            <div className="spotlight-banner">
              <span className="spotlight-label">Spotlight</span>
              <div>
                <strong>{spotlight.name}</strong>
                <p>{spotlight.area.name} · {spotlight.opens_at} - {spotlight.closes_at} · {formatDistance(spotlight.distanceMiles)}</p>
              </div>
              <a className="cta-link" href={`/venues/${spotlight.slug}`}>Open venue</a>
            </div>
          ) : null}
        </div>
        <MapPanel areas={areas.data ?? []} venues={venuesWithDistance} selectedArea={filters.area} onSelectArea={(slug) => setFilters((current) => ({ ...current, area: slug }))} />
      </section>

      <section className="filter-surface">
        <div className="section-topline">
          <span>Filter the night</span>
          <small>Sort by vibe, spend, timing, or what is near you</small>
        </div>
        <div className="filter-grid">
          <label>Date<input type="date" value={filters.date} onChange={(event) => setFilters({ ...filters, date: event.target.value })} /></label>
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
            <button className={classNames("toggle-pill", filters.open_now && "active")} type="button" onClick={() => setFilters({ ...filters, open_now: !filters.open_now })}>
              <span />
            </button>
          </label>
        </div>
      </section>

      <section className="events-toolbar">
        <div className="tab-group">
          <button className={classNames("tab-button", activeTab === "all" && "active")} onClick={() => setActiveTab("all")}>All events</button>
          <button className={classNames("tab-button", activeTab === "nearby" && "active")} onClick={() => { setActiveTab("nearby"); if (!location.coords) location.requestLocation(); }}>Events close by</button>
        </div>
        <div className="nearby-state">
          {location.coords ? <span>Nearby results use your current location.</span> : <span>{location.error ?? "Enable location to show exact distance from you."}</span>}
        </div>
      </section>

      <section className="listing-grid">
        <div className="listing-column">
          <div className="section-headline">
            <h2>Venues in view</h2>
            <p>Each card now shows how far the venue is from you.</p>
          </div>
          {venues.loading ? <p className="empty-message">Loading venues...</p> : null}
          <div className="card-stack">
            {venuesWithDistance.map((venue) => (
              <a key={venue.id} href={`/venues/${venue.slug}`} className="venue-tile">
                <div className="tile-topline">
                  <span>{venue.type}</span>
                  <span>{venue.area.name}</span>
                  <span>{venue.price_band}</span>
                </div>
                <h3>{venue.name}</h3>
                <p>{venue.description}</p>
                <dl className="data-points">
                  <div><dt>Hours</dt><dd>{venue.opens_at} - {venue.closes_at}</dd></div>
                  <div><dt>Address</dt><dd>{venue.address}</dd></div>
                  <div><dt>Next event</dt><dd>{formatDateTime(venue.next_event_start)}</dd></div>
                  <div><dt>Distance</dt><dd>{formatDistance(venue.distanceMiles)}</dd></div>
                  <div><dt>Freshness</dt><dd>{venue.source.status} · {Math.round(venue.source.confidence * 100)}%</dd></div>
                </dl>
              </a>
            ))}
          </div>
        </div>

        <div className="listing-column">
          <div className="section-headline">
            <h2>{activeTab === "nearby" ? "Events close by" : "Upcoming events"}</h2>
            <p>Each event card now includes distance from your current location.</p>
          </div>
          {events.loading ? <p className="empty-message">Loading events...</p> : null}
          <div className="card-stack">
            {displayedEvents.map((event: EventItem & { distanceMiles: number | null }) => (
              <article key={event.id} className="event-tile">
                <div className="tile-topline">
                  <span>{event.genre}</span>
                  <span>{event.venue.name}</span>
                  <span>{event.price_label}</span>
                </div>
                <h3>{event.title}</h3>
                <p>{event.description}</p>
                <dl className="data-points">
                  <div><dt>Starts</dt><dd>{formatDateTime(event.start_at)}</dd></div>
                  <div><dt>Venue hours</dt><dd>{event.venue.opens_at} - {event.venue.closes_at}</dd></div>
                  <div><dt>Area</dt><dd>{event.venue.area.name}</dd></div>
                  <div><dt>Distance</dt><dd>{formatDistance(event.distanceMiles)}</dd></div>
                  <div><dt>Source</dt><dd>{event.source.status} · {formatDateTime(event.source.last_verified_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</dd></div>
                </dl>
                <div className="action-row">
                  <a className="inline-route" href={`/events/${event.id}`}>Event page</a>
                  <a className="inline-route subtle" href={mapsUrl(event.venue.coordinates)} target="_blank" rel="noreferrer">Directions</a>
                </div>
              </article>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}

function VenuePage({ slug }: { slug: string }) {
  const { theme, toggleTheme } = useTheme();
  const location = useCurrentLocation();
  const { data, loading, error } = useFetch<VenueDetail>(`/api/venues/${slug}`, [slug]);
  const [claim, setClaim] = useState({ claimant_name: "", claimant_email: "", message: "" });
  const [claimState, setClaimState] = useState<{ loading: boolean; message: string | null; error: string | null }>({ loading: false, message: null, error: null });

  async function submitClaim(event: any) {
    event.preventDefault();
    setClaimState({ loading: true, message: null, error: null });
    const response = await fetch("/claims", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ venue_id: data?.id, ...claim }),
    });
    const payload = await response.json();
    if (!response.ok) {
      setClaimState({ loading: false, message: null, error: payload.error ?? "Claim failed." });
      return;
    }
    setClaim({ claimant_name: "", claimant_email: "", message: "" });
    setClaimState({ loading: false, message: payload.message, error: null });
  }

  return (
    <div className="nightlife-app">
      <Header theme={theme} onToggleTheme={toggleTheme} onUseLocation={location.requestLocation} hasLocation={Boolean(location.coords)} />
      <a className="back-link" href="/">Back to town view</a>
      {loading ? <p className="empty-message">Loading venue...</p> : null}
      {error ? <p className="empty-message">{error}</p> : null}
      {data ? (
        <>
          <section className="venue-hero">
            <div className="hero-panel venue-main">
              <p className="kicker">{data.type} · {data.area.name}</p>
              <h1>{data.name}</h1>
              <p className="lede">{data.description}</p>
              <div className="pill-row">
                <span>{data.price_band}</span>
                <span>{data.opens_at} - {data.closes_at}</span>
                <span>{data.source.status}</span>
                <span>{formatDistance(location.coords ? distanceMiles(location.coords, data.coordinates) : null)}</span>
              </div>
              <div className="action-row top-actions">
                <a className="inline-route" href={mapsUrl(data.coordinates)} target="_blank" rel="noreferrer">Directions</a>
              </div>
            </div>
            <div className="hero-panel info-grid">
              <div><strong>Address</strong><span>{data.address}</span></div>
              <div><strong>Verified</strong><span>{formatDateTime(data.source.last_verified_at, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</span></div>
              <div><strong>Confidence</strong><span>{Math.round(data.source.confidence * 100)}%</span></div>
              <div><strong>Distance</strong><span>{formatDistance(location.coords ? distanceMiles(location.coords, data.coordinates) : null)}</span></div>
            </div>
          </section>

          <section className="listing-grid">
            <div className="listing-column">
              <div className="section-headline">
                <h2>Opening hours</h2>
                <p>Overnight sessions are called out clearly.</p>
              </div>
              <div className="card-stack">
                {data.opening_hours.map((hour) => (
                  <div key={hour.day_of_week} className="hour-row">
                    <span>{DAY_LABELS[hour.day_of_week]}</span>
                    <strong>{hour.open_time} - {hour.close_time}{hour.is_overnight ? " overnight" : ""}</strong>
                  </div>
                ))}
              </div>
            </div>

            <div className="listing-column">
              <div className="section-headline">
                <h2>Published events</h2>
                <p>Each event keeps the directions flow one tap away.</p>
              </div>
              <div className="card-stack">
                {data.events.map((event) => (
                  <article key={event.id} className="event-tile">
                    <div className="tile-topline">
                      <span>{event.genre}</span>
                      <span>{event.price_label}</span>
                    </div>
                    <h3>{event.title}</h3>
                    <p>{event.description}</p>
                    <p className="mini-copy">{formatDateTime(event.start_at)} to {formatDateTime(event.end_at, { hour: "2-digit", minute: "2-digit" })}</p>
                    <div className="action-row">
                      <a className="inline-route" href={`/events/${event.id}`}>Open event page</a>
                      <a className="inline-route subtle" href={mapsUrl(data.coordinates)} target="_blank" rel="noreferrer">Directions</a>
                    </div>
                  </article>
                ))}
              </div>
            </div>
          </section>

          <section className="claim-surface">
            <div className="section-headline">
              <h2>Claim this venue</h2>
              <p>Venue teams can request ownership so they can keep listings fresh.</p>
            </div>
            <form className="claim-grid" onSubmit={submitClaim}>
              <label>Name<input value={claim.claimant_name} onChange={(event: any) => setClaim({ ...claim, claimant_name: event.target.value })} required /></label>
              <label>Email<input type="email" value={claim.claimant_email} onChange={(event: any) => setClaim({ ...claim, claimant_email: event.target.value })} required /></label>
              <label className="claim-message">Message<textarea rows={4} value={claim.message} onChange={(event: any) => setClaim({ ...claim, message: event.target.value })} required /></label>
              <button type="submit" disabled={claimState.loading}>{claimState.loading ? "Submitting..." : "Submit claim request"}</button>
            </form>
            {claimState.message ? <p className="success-note">{claimState.message}</p> : null}
            {claimState.error ? <p className="error-note">{claimState.error}</p> : null}
          </section>
        </>
      ) : null}
    </div>
  );
}

function EventPage({ eventId }: { eventId: number }) {
  const { theme, toggleTheme } = useTheme();
  const location = useCurrentLocation();
  const { data, loading, error } = useFetch<EventItem>(`/api/events/${eventId}`, [eventId]);

  return (
    <div className="nightlife-app">
      <Header theme={theme} onToggleTheme={toggleTheme} onUseLocation={location.requestLocation} hasLocation={Boolean(location.coords)} />
      <a className="back-link" href="/">Back to town view</a>
      {loading ? <p className="empty-message">Loading event...</p> : null}
      {error ? <p className="empty-message">{error}</p> : null}
      {data ? (
        <>
          <section className="venue-hero">
            <div className="hero-panel venue-main">
              <p className="kicker">{data.genre} · {data.venue.area.name}</p>
              <h1>{data.title}</h1>
              <p className="lede">{data.description}</p>
              <div className="pill-row">
                <span>{data.price_label}</span>
                <span>{formatDateTime(data.start_at)}</span>
                <span>{data.venue.name}</span>
                <span>{formatDistance(location.coords ? distanceMiles(location.coords, data.venue.coordinates) : null)}</span>
              </div>
              <div className="action-row top-actions">
                <a className="inline-route" href={mapsUrl(data.venue.coordinates)} target="_blank" rel="noreferrer">Directions</a>
                <a className="inline-route subtle" href={`/venues/${data.venue.slug}`}>Venue page</a>
              </div>
            </div>
            <div className="hero-panel info-grid">
              <div><strong>Venue</strong><span>{data.venue.name}</span></div>
              <div><strong>Address</strong><span>{data.venue.address}</span></div>
              <div><strong>Venue hours</strong><span>{data.venue.opens_at} - {data.venue.closes_at}</span></div>
              <div><strong>Distance</strong><span>{formatDistance(location.coords ? distanceMiles(location.coords, data.venue.coordinates) : null)}</span></div>
            </div>
          </section>

          <section className="event-detail-grid">
            <div className="spotlight-card">
              <div className="section-headline">
                <h2>Before you go</h2>
                <p>Everything needed to get there quickly.</p>
              </div>
              <dl className="data-points">
                <div><dt>Starts</dt><dd>{formatDateTime(data.start_at)}</dd></div>
                <div><dt>Ends</dt><dd>{formatDateTime(data.end_at, { weekday: "short", hour: "2-digit", minute: "2-digit" })}</dd></div>
                <div><dt>Price</dt><dd>{data.price_label}</dd></div>
                <div><dt>Freshness</dt><dd>{data.source.status} · {Math.round(data.source.confidence * 100)}%</dd></div>
              </dl>
            </div>
            <div className="spotlight-card">
              <div className="section-headline">
                <h2>Directions</h2>
                <p>Open walking directions straight in your maps app.</p>
              </div>
              <div className="map-preview-card">
                <div className="map-preview-dot" />
                <div>
                  <strong>{data.venue.name}</strong>
                  <p>{data.venue.address}</p>
                </div>
              </div>
              <a className="wide-action" href={mapsUrl(data.venue.coordinates)} target="_blank" rel="noreferrer">Open directions</a>
            </div>
          </section>
        </>
      ) : null}
    </div>
  );
}

function App() {
  if (initialConfig.page === "venue" && initialConfig.venueSlug) return <VenuePage slug={initialConfig.venueSlug} />;
  if (initialConfig.page === "event" && initialConfig.eventId) return <EventPage eventId={initialConfig.eventId} />;
  return <HomePage />;
}

ReactDOM.createRoot(document.getElementById("app-root")).render(<App />);
