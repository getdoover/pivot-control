// Pure geometry and data shaping for the pivot map: no React, no network, so it is
// unit-tested directly (test/geo.test.ts).

export interface LatLon {
  lat: number;
  lon: number;
}

export interface TrackPoint extends LatLon {
  t: number; // unix ms
}

export interface TagRef {
  app_name?: string | null;
  tag_name?: string | null;
}

export const POSITION_FROM_LOCATION = "Location channel";

const EARTH_RADIUS_M = 6_371_008.8;

// Closer to the centre than this, a GPS fix can't give a meaningful bearing.
export const MIN_ARM_LENGTH_M = 10;

const COMPASS = [
  "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
];

const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export function toNumber(x: unknown): number | null {
  if (typeof x === "number") return Number.isFinite(x) ? x : null;
  if (typeof x === "string" && x.trim() !== "") {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** A usable position, or null (missing, out of range, or the 0,0 no-fix placeholder). */
export function toLatLon(lat: unknown, lon: unknown): LatLon | null {
  const la = toNumber(lat);
  const lo = toNumber(lon);
  if (la == null || lo == null) return null;
  if (la < -90 || la > 90 || lo < -180 || lo > 180) return null;
  if (la === 0 && lo === 0) return null;
  return { lat: la, lon: lo };
}

/** Great-circle (haversine) distance in metres. */
export function distanceM(a: LatLon, b: LatLon): number {
  const p1 = rad(a.lat);
  const p2 = rad(b.lat);
  const dp = p2 - p1;
  const dl = rad(b.lon - a.lon);
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Initial bearing a → b: degrees, 0 = North, clockwise, [0, 360). */
export function bearingDeg(a: LatLon, b: LatLon): number {
  const p1 = rad(a.lat);
  const p2 = rad(b.lat);
  const dl = rad(b.lon - a.lon);
  const y = Math.sin(dl) * Math.cos(p2);
  const x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return ((deg(Math.atan2(y, x)) % 360) + 360) % 360;
}

/** The pivot's angle from its centre to the end tower, or null without a real arm. */
export function armAngle(centre: LatLon | null, tower: LatLon | null): number | null {
  if (!centre || !tower) return null;
  if (distanceM(centre, tower) < MIN_ARM_LENGTH_M) return null;
  return bearingDeg(centre, tower);
}

export function headingText(angle: number | null): string | null {
  if (angle == null || !Number.isFinite(angle)) return null;
  const a = ((angle % 360) + 360) % 360;
  return `${Math.round(a) % 360}° ${COMPASS[Math.floor(a / 22.5 + 0.5) % 16]}`;
}

/** The pivot centre: the configured one, else the device's fixed location. */
export function resolveCentre(
  cfgLat: unknown,
  cfgLon: unknown,
  fixed: { latitude?: unknown; longitude?: unknown } | null | undefined,
): { centre: LatLon | null; from: "config" | "device" | null } {
  const configured = toLatLon(cfgLat, cfgLon);
  if (configured) return { centre: configured, from: "config" };
  const device = fixed ? toLatLon(fixed.latitude, fixed.longitude) : null;
  if (device) return { centre: device, from: "device" };
  return { centre: null, from: null };
}

/** A tag's value from a tag_values-shaped object: `{app: {tag: v}}` or flat `{"app.tag": v}`. */
export function tagValue(values: Record<string, unknown> | null | undefined, ref: TagRef): unknown {
  if (!values || !ref.app_name || !ref.tag_name) return undefined;
  const flat = values[`${ref.app_name}.${ref.tag_name}`];
  if (flat !== undefined) return flat;
  const app = values[ref.app_name];
  if (app && typeof app === "object") return (app as Record<string, unknown>)[ref.tag_name];
  return undefined;
}

/**
 * Track points from timeseries rows, oldest first. Location rows carry `{lat, long}`; tag
 * rows carry the two tags. A row with only one coordinate is completed from the last seen
 * value of the other; repeated identical positions are collapsed to the first.
 */
export function buildTrack(
  rows: Array<{ t: number; value: unknown }>,
  mode: "location" | "tags",
  latRef: TagRef,
  lonRef: TagRef,
): TrackPoint[] {
  const sorted = rows
    .filter((r) => Number.isFinite(r.t) && r.value && typeof r.value === "object")
    .sort((a, b) => a.t - b.t);
  const out: TrackPoint[] = [];
  let lastLat: unknown;
  let lastLon: unknown;
  for (const r of sorted) {
    const v = r.value as Record<string, unknown>;
    let lat: unknown;
    let lon: unknown;
    if (mode === "location") {
      lat = v.lat ?? v.latitude;
      lon = v.long ?? v.lon ?? v.longitude;
    } else {
      lat = tagValue(v, latRef);
      lon = tagValue(v, lonRef);
    }
    if (lat !== undefined && lat !== null) lastLat = lat;
    if (lon !== undefined && lon !== null) lastLon = lon;
    const p = toLatLon(lastLat, lastLon);
    if (!p) continue;
    const prev = out[out.length - 1];
    if (prev && prev.lat === p.lat && prev.lon === p.lon) continue;
    out.push({ ...p, t: r.t });
  }
  return out;
}

/** Map zoom that fits a span of `metres` across a ~`px`-pixel box at this latitude. */
export function zoomForSpan(lat: number, metres: number, px = 320): number {
  const mPerPxAtZ0 = (156_543.03392 * Math.cos(rad(lat))) || 1;
  const z = Math.log2((mPerPxAtZ0 * px) / Math.max(metres, 50));
  return Math.max(3, Math.min(18, Math.floor(z)));
}
