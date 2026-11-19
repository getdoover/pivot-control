import "leaflet/dist/leaflet.css";
import "./styles.css";

import { useEffect, useMemo, useRef } from "react";
import L from "leaflet";

import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";

import { useAgentChannel, useDooverClient } from "doover-js/react";
import { extractSnowflakeId, generateSnowflakeIdAtTime } from "doover-js";
import { useQuery } from "@tanstack/react-query";

import {
  POSITION_FROM_LOCATION,
  armAngle,
  buildTrack,
  distanceM,
  headingText,
  resolveCentre,
  tagValue,
  toLatLon,
  toNumber,
  type LatLon,
  type TagRef,
  type TrackPoint,
} from "./lib/geo";

interface UiElement {
  app_key?: string;
  [key: string]: unknown;
}

interface AppConfig {
  pivot_centre_lat?: number | null;
  pivot_centre_lon?: number | null;
  wetted_radius_m?: number | null;
  track_hours?: number | null;
  position_source?: string | null;
  latitude_source?: TagRef | null;
  longitude_source?: TagRef | null;
}

type TagValues = Record<string, Record<string, unknown>>;

const PAGE_LIMIT = 1500;
const MAX_PAGES = 4;
const REFRESH_MS = 60_000;

// Keyless satellite imagery, so the map renders with no per-deployment setup.
const IMAGERY_URL =
  "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const IMAGERY_ATTRIBUTION =
  "Imagery &copy; Esri, Maxar, Earthstar Geographics and the GIS User Community";

const COLOURS = {
  centre: "#ffffff",
  arm: "#facc15",
  tower: "#f97316",
  track: "#38bdf8",
  circle: "#e2e8f0",
};

function ago(ms: number | null): string | null {
  if (ms == null) return null;
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return `${Math.round(s / 60)} min ago`;
  if (s < 172_800) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86_400)} days ago`;
}

function statusClass(state: unknown): string {
  if (state === "running") return "pcw-dot running";
  if (state === "stopped") return "pcw-dot stopped";
  return "pcw-dot unknown";
}

function useTrack(
  agentId: string | undefined,
  mode: "location" | "tags",
  latRef: TagRef,
  lonRef: TagRef,
  hours: number,
) {
  const client = useDooverClient();
  const apps = Array.from(
    new Set([latRef.app_name, lonRef.app_name].filter((a): a is string => Boolean(a))),
  );
  return useQuery({
    queryKey: ["pivot-control-track", agentId, mode, apps, latRef.tag_name, lonRef.tag_name, hours],
    enabled: Boolean(agentId) && (mode === "location" || apps.length > 0),
    refetchInterval: REFRESH_MS,
    queryFn: async (): Promise<TrackPoint[]> => {
      const now = Date.now();
      const after = generateSnowflakeIdAtTime(new Date(now - hours * 3_600_000));
      let before = generateSnowflakeIdAtTime(new Date(now + 120_000));
      const rows: Array<{ t: number; value: unknown }> = [];
      for (let page = 0; page < MAX_PAGES; page++) {
        const res = await client.messages.getTimeseries(
          agentId!,
          mode === "location" ? "location" : "tag_values",
          {
            before,
            after,
            field_name: mode === "location" ? ["lat", "long"] : apps,
            limit: PAGE_LIMIT,
          },
        );
        for (const r of res.results ?? []) {
          rows.push({ t: extractSnowflakeId(r.message_id).timestamp, value: r.value });
        }
        if (!res.next) break;
        before = res.next;
      }
      return buildTrack(rows, mode, latRef, lonRef);
    },
  });
}

function useFixedLocation(agentId: string | undefined, enabled: boolean) {
  const client = useDooverClient();
  return useQuery({
    queryKey: ["pivot-control-fixed-location", agentId],
    enabled: Boolean(agentId) && enabled,
    staleTime: 10 * 60_000,
    queryFn: async () => {
      const res = await client.agents.listAgents();
      const agent = (res.agents ?? []).find((a) => String(a.id) === String(agentId));
      return agent?.fixed_location ?? null;
    },
  });
}

export function PivotMap({
  centre,
  tower,
  track,
  radiusM,
}: {
  centre: LatLon | null;
  tower: LatLon | null;
  track: TrackPoint[];
  radiusM: number | null;
}) {
  const divRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const fittedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!divRef.current || mapRef.current) return;
    const map = L.map(divRef.current, {
      zoomControl: true,
      attributionControl: true,
      scrollWheelZoom: false,
    });
    L.tileLayer(IMAGERY_URL, {
      maxNativeZoom: 18,
      maxZoom: 20,
      attribution: IMAGERY_ATTRIBUTION,
    }).addTo(map);
    layerRef.current = L.layerGroup().addTo(map);
    mapRef.current = map;
    // The panel may still be laying out (or collapsed) when the map mounts.
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(divRef.current);
    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      layerRef.current = null;
      fittedRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    const layer = layerRef.current;
    if (!map || !layer) return;
    layer.clearLayers();

    const ll = (p: LatLon): L.LatLngTuple => [p.lat, p.lon];

    if (centre && radiusM && radiusM > 0) {
      L.circle(ll(centre), {
        radius: radiusM,
        color: COLOURS.circle,
        weight: 1.5,
        dashArray: "6 6",
        fillColor: COLOURS.track,
        fillOpacity: 0.08,
        interactive: false,
      }).addTo(layer);
    }
    if (track.length >= 2) {
      L.polyline(track.map(ll), {
        color: COLOURS.track,
        weight: 3,
        opacity: 0.9,
      })
        .bindTooltip("Recent track")
        .addTo(layer);
    }
    if (centre && tower) {
      L.polyline([ll(centre), ll(tower)], {
        color: COLOURS.arm,
        weight: 4,
        opacity: 0.95,
        interactive: false,
      }).addTo(layer);
    }
    if (centre) {
      L.circleMarker(ll(centre), {
        radius: 6,
        color: "#111827",
        weight: 2,
        fillColor: COLOURS.centre,
        fillOpacity: 1,
      })
        .bindTooltip("Pivot centre")
        .addTo(layer);
    }
    if (tower) {
      const arm = centre ? ` · ${Math.round(distanceM(centre, tower))} m from centre` : "";
      L.circleMarker(ll(tower), {
        radius: 8,
        color: "#111827",
        weight: 2,
        fillColor: COLOURS.tower,
        fillOpacity: 1,
      })
        .bindTooltip(`End tower${arm}`)
        .addTo(layer);
    }

    // Fit once per centre / first tower fix, so live updates don't fight the user's zoom.
    const fitKey = `${centre?.lat},${centre?.lon}|${tower ? "t" : ""}|${radiusM ?? ""}`;
    if (fittedRef.current === fitKey) return;
    const pts: L.LatLngTuple[] = [];
    if (centre) pts.push(ll(centre));
    if (tower) pts.push(ll(tower));
    if (!pts.length && track.length) pts.push(ll(track[track.length - 1]));
    if (!pts.length) return;
    fittedRef.current = fitKey;
    const anchor = centre ?? tower ?? track[track.length - 1];
    let span = 0;
    if (centre && tower) span = 2 * distanceM(centre, tower);
    if (centre && radiusM) span = Math.max(span, 2 * radiusM);
    if (span > 0 && centre) {
      // The whole circle the arm sweeps, so the tower stays in view as it moves.
      map.fitBounds(L.latLng(centre.lat, centre.lon).toBounds(span * 1.1), { padding: [8, 8] });
    } else {
      map.setView(ll(anchor), 16);
    }
  }, [centre, tower, track, radiusM]);

  return <div ref={divRef} className="pcw-map" />;
}

function PivotControlInner({ uiElement }: { uiElement?: UiElement }) {
  const params = useRemoteParams();
  const agentId = params.agentId;
  const appKey = uiElement?.app_key;

  const { data: depCfg, isLoading: cfgLoading } = useAgentChannel<{
    applications?: Record<string, AppConfig>;
  }>(agentId, "deployment_config");
  const cfg: AppConfig = (appKey ? depCfg?.applications?.[appKey] : undefined) ?? {};

  const mode: "location" | "tags" =
    cfg.position_source === POSITION_FROM_LOCATION ? "location" : "tags";
  const latRef: TagRef = {
    app_name: cfg.latitude_source?.app_name ?? "gps_tracker_1",
    tag_name: cfg.latitude_source?.tag_name ?? "latitude",
  };
  const lonRef: TagRef = {
    app_name: cfg.longitude_source?.app_name ?? "gps_tracker_1",
    tag_name: cfg.longitude_source?.tag_name ?? "longitude",
  };
  const hours = Math.min(720, Math.max(1, toNumber(cfg.track_hours) ?? 24));
  const radiusM = toNumber(cfg.wetted_radius_m);

  const { data: tagValues } = useAgentChannel<TagValues>(agentId, "tag_values");
  const { data: location } = useAgentChannel<Record<string, unknown>>(
    mode === "location" ? agentId : undefined,
    "location",
  );

  const configuredCentre = toLatLon(cfg.pivot_centre_lat, cfg.pivot_centre_lon);
  const fixed = useFixedLocation(agentId, !configuredCentre);
  const { centre, from: centreFrom } = useMemo(
    () => resolveCentre(cfg.pivot_centre_lat, cfg.pivot_centre_lon, fixed.data),
    [cfg.pivot_centre_lat, cfg.pivot_centre_lon, fixed.data],
  );

  const trackQuery = useTrack(agentId, mode, latRef, lonRef, hours);
  const track = trackQuery.data ?? [];

  const liveTower =
    mode === "location"
      ? toLatLon(location?.lat, location?.long ?? location?.lon)
      : toLatLon(tagValue(tagValues, latRef), tagValue(tagValues, lonRef));
  const lastPoint = track.length ? track[track.length - 1] : null;
  const towerKey = liveTower
    ? `${liveTower.lat},${liveTower.lon}`
    : lastPoint
      ? `${lastPoint.lat},${lastPoint.lon}`
      : "";
  const tower = useMemo<LatLon | null>(
    () => liveTower ?? (lastPoint ? { lat: lastPoint.lat, lon: lastPoint.lon } : null),
    [towerKey],
  );

  const own = (appKey && tagValues?.[appKey]) || {};
  const status = typeof own.status === "string" ? own.status : "No reading yet";
  const reportedAngle = toNumber(own.angle_deg);
  const angle = reportedAngle ?? armAngle(centre, tower);
  const fixTs =
    toNumber(tagValue(tagValues, { app_name: latRef.app_name, tag_name: "last_fix_ts" })) ??
    lastPoint?.t ??
    null;

  if (cfgLoading) return <div className="pcw-msg">Loading…</div>;
  if (!appKey) return <div className="pcw-msg">Map is missing its app key.</div>;

  const noPosition = !centre && !tower && track.length === 0;

  return (
    <div className="pcw">
      <div className="pcw-header">
        <span className={statusClass(own.state)} />
        <span className="pcw-status">{status}</span>
        {angle != null && <span className="pcw-angle">{headingText(angle)}</span>}
        <span className="pcw-spacer" />
        {fixTs != null && <span className="pcw-note">GPS {ago(fixTs)}</span>}
      </div>
      {noPosition ? (
        <div className="pcw-msg">
          No position yet. Set the pivot centre (or the device's fixed location) and a GPS
          source in this app's config.
        </div>
      ) : (
        <PivotMap
          centre={centre}
          tower={tower}
          track={track}
          radiusM={radiusM && radiusM > 0 ? radiusM : null}
        />
      )}
      <div className="pcw-legend">
        <span>
          <i className="pcw-key centre" /> Centre{centreFrom === "device" ? " (device location)" : ""}
        </span>
        <span>
          <i className="pcw-key tower" /> End tower
        </span>
        <span>
          <i className="pcw-key track" /> Last {hours % 24 === 0 && hours >= 48 ? `${hours / 24} days` : `${hours} h`}
        </span>
        {!tower && <span className="pcw-note">No GPS fix yet</span>}
      </div>
    </div>
  );
}

export default function PivotControlWidget(props: { uiElement?: UiElement }) {
  return (
    <RemoteComponentWrapper>
      <PivotControlInner {...props} />
    </RemoteComponentWrapper>
  );
}
