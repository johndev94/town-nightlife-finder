import type { Coords } from './types'

export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export function formatDateTime(value: string | null, options?: Intl.DateTimeFormatOptions) {
  if (!value) return 'TBC'
  return new Intl.DateTimeFormat(
    'en-GB',
    options ?? { weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' },
  ).format(new Date(value))
}

export function classNames(...values: Array<string | false | null | undefined>) {
  return values.filter(Boolean).join(' ')
}

export function mapsUrl(destination: Coords) {
  return `https://www.google.com/maps/dir/?api=1&destination=${destination.lat},${destination.lng}&travelmode=walking`
}

export function distanceMiles(from: Coords, to: Coords) {
  const toRadians = (value: number) => (value * Math.PI) / 180
  const earthRadiusMiles = 3958.8
  const latDelta = toRadians(to.lat - from.lat)
  const lngDelta = toRadians(to.lng - from.lng)
  const a =
    Math.sin(latDelta / 2) ** 2 +
    Math.cos(toRadians(from.lat)) * Math.cos(toRadians(to.lat)) * Math.sin(lngDelta / 2) ** 2
  return 2 * earthRadiusMiles * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

export function formatDistance(distance: number | null | undefined) {
  if (distance === null || distance === undefined) return 'Use location'
  if (distance < 0.15) return `${Math.round(distance * 5280)} ft away`
  return `${distance.toFixed(1)} miles away`
}
