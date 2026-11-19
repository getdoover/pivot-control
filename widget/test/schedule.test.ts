import { test } from "node:test";
import assert from "node:assert/strict";

import { blankStep, stepErrors, stepView, type Schedule } from "../src/schedule/model.ts";

const D = { speed: 50, wet: true };

test("step errors match the processor's", () => {
  const s = blankStep(D);
  assert.deepEqual(stepErrors(s), ["Choose a stop angle or a run time"]);
  assert.deepEqual(stepErrors({ ...s, angle: "400", speed: "0" }), ["Speed must be 1–100 %", "Stop angle must be 0–360°"]);
  assert.deepEqual(stepErrors({ ...s, end: "time", hours: "0" }), ["Run time must be more than 0"]);
  assert.deepEqual(stepErrors({ ...s, end: "time", hours: "9" }, 8), ["Run time can't be over the 8 h maximum"]);
  assert.deepEqual(stepErrors({ ...s, angle: "180", delay: "-1" }), ["Start delay can't be negative"]);
  assert.deepEqual(stepErrors({ ...s, angle: "0" }), []);
});

const T0 = 1_795_100_000_000;
const MIN = 60_000;

function sched(over: Partial<Schedule> = {}): Schedule {
  return {
    id: "a",
    mode: "detailed",
    steps: [{ direction: "forward", wet: true, speed_percent: 50, end: "time", stop_angle_deg: null, run_hours: 1, delay_min: 10 }],
    status: "running",
    paused: false,
    started_ts: T0,
    started_by: null,
    paused_ts: null,
    paused_ms: 0,
    ended_ts: null,
    progress: {
      step_index: 0,
      step_started_ts: T0,
      paused_ms_at_step: 0,
      waiting: true,
      fraction: 0,
      remaining_deg: null,
      remaining_s: null,
      estimated: true,
      updated_ts: T0,
    },
    ...over,
  };
}

test("time steps tick: delay, then run time, less pauses", () => {
  assert.equal(stepView(sched(), T0 + 5 * MIN).remainingS, 300);
  assert.equal(stepView(sched(), T0 + 40 * MIN).fraction, 0.5);
  // Paused at 40 min, still paused at 90: frozen at half.
  assert.equal(stepView(sched({ paused: true, paused_ts: T0 + 40 * MIN }), T0 + 90 * MIN).fraction, 0.5);
  // Resumed after an hour's pause.
  assert.equal(stepView(sched({ paused_ms: 60 * MIN }), T0 + 100 * MIN).fraction, 0.5);
});
