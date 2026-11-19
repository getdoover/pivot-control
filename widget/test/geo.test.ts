import { test } from "node:test";
import assert from "node:assert/strict";

import {
  armAngle,
  bearingDeg,
  buildTrack,
  distanceM,
  headingText,
  resolveCentre,
  tagValue,
  toLatLon,
  zoomForSpan,
} from "../src/lib/geo.ts";

const CENTRE = { lat: -22.551015, lon: 149.06091 };
const M_PER_DEG = 111_195;

function offset(north: number, east: number) {
  return {
    lat: CENTRE.lat + north / M_PER_DEG,
    lon: CENTRE.lon + east / M_PER_DEG / Math.cos((CENTRE.lat * Math.PI) / 180),
  };
}

const near = (a: number, b: number, tol: number) =>
  assert.ok(Math.min(Math.abs(a - b), 360 - Math.abs(a - b)) < tol, `${a} != ${b}`);

test("bearing on the compass points", () => {
  near(bearingDeg(CENTRE, offset(400, 0)), 0, 0.05);
  near(bearingDeg(CENTRE, offset(0, 400)), 90, 0.05);
  near(bearingDeg(CENTRE, offset(-400, 0)), 180, 0.05);
  near(bearingDeg(CENTRE, offset(0, -400)), 270, 0.05);
  near(bearingDeg(CENTRE, offset(283, -283)), 315, 0.05);
});

test("matches the processor on a real fix", () => {
  // Same case as tests/test_model.py: 308.5 deg.
  const a = armAngle(CENTRE, { lat: -22.548267, lon: 149.057164 });
  assert.ok(a != null && Math.abs(a - 308.46) < 0.05, String(a));
});

test("distance", () => {
  assert.ok(Math.abs(distanceM(CENTRE, offset(300, 400)) - 500) < 0.5);
  assert.equal(distanceM(CENTRE, CENTRE), 0);
});

test("no arm angle without both points or too close to the centre", () => {
  assert.equal(armAngle(null, CENTRE), null);
  assert.equal(armAngle(CENTRE, null), null);
  assert.equal(armAngle(CENTRE, offset(3, 3)), null);
});

test("heading text", () => {
  assert.equal(headingText(308.46), "308° NW");
  assert.equal(headingText(359.7), "0° N");
  assert.equal(headingText(null), null);
});

test("lat/lon validation", () => {
  assert.deepEqual(toLatLon("-22.5", 149), { lat: -22.5, lon: 149 });
  assert.equal(toLatLon(0, 0), null);
  assert.equal(toLatLon(95, 0), null);
  assert.equal(toLatLon(null, 149), null);
  assert.equal(toLatLon("", 149), null);
});

test("centre from config, else the device's fixed location", () => {
  assert.deepEqual(resolveCentre(-22.5, 149.1, { latitude: 1, longitude: 2 }), {
    centre: { lat: -22.5, lon: 149.1 },
    from: "config",
  });
  assert.deepEqual(resolveCentre(null, undefined, { latitude: -22.6, longitude: 149.2 }), {
    centre: { lat: -22.6, lon: 149.2 },
    from: "device",
  });
  assert.deepEqual(resolveCentre(null, null, null), { centre: null, from: null });
});

test("tag value from nested and flat shapes", () => {
  const ref = { app_name: "gps", tag_name: "latitude" };
  assert.equal(tagValue({ gps: { latitude: -22 } }, ref), -22);
  assert.equal(tagValue({ "gps.latitude": -23 }, ref), -23);
  assert.equal(tagValue({}, ref), undefined);
  assert.equal(tagValue({ gps: { latitude: 1 } }, { app_name: null, tag_name: "latitude" }), undefined);
});

test("track from location rows: sorted, deduplicated, bad fixes dropped", () => {
  const rows = [
    { t: 3, value: { lat: -22.2, long: 149.2 } },
    { t: 1, value: { lat: -22.1, long: 149.1 } },
    { t: 2, value: { lat: -22.1, long: 149.1 } },
    { t: 4, value: { lat: 0, long: 0 } },
  ];
  const track = buildTrack(rows, "location", {}, {});
  assert.deepEqual(track.map((p) => p.t), [1, 3]);
});

test("track from tag rows fills a missing coordinate from the last seen", () => {
  const lat = { app_name: "gps", tag_name: "latitude" };
  const lon = { app_name: "gps", tag_name: "longitude" };
  const rows = [
    { t: 1, value: { "gps.latitude": -22.1, "gps.longitude": 149.1 } },
    { t: 2, value: { "gps.latitude": -22.2 } },
    { t: 3, value: { gps: { other: 1 } } },
  ];
  const track = buildTrack(rows, "tags", lat, lon);
  assert.deepEqual(track, [
    { lat: -22.1, lon: 149.1, t: 1 },
    { lat: -22.2, lon: 149.1, t: 2 },
  ]);
});

test("zoom fits the arm", () => {
  const z = zoomForSpan(-22.5, 1000);
  assert.ok(z >= 14 && z <= 17, String(z));
});
