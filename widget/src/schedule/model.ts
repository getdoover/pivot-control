// The schedule as the Pivot Control processor stores it (tags schedule_active /
// schedule_history), the editor's draft steps, and the checks the processor
// makes again on Go. Messages here match the processor's word for word.

export type Direction = "forward" | "reverse";
export type StepEnd = "angle" | "time";
export type Mode = "simple" | "detailed";

/** A step as stored and sent. */
export interface Step {
  direction: Direction;
  wet: boolean;
  speed_percent: number;
  end: StepEnd;
  stop_angle_deg: number | null;
  run_hours: number | null;
  delay_min: number | null;
}

export interface Progress {
  step_index: number;
  step_started_ts: number | null;
  paused_ms_at_step: number | null;
  start_angle_deg?: number | null;
  turned_deg?: number | null;
  waiting: boolean;
  fraction: number | null;
  remaining_deg: number | null;
  remaining_s: number | null;
  estimated: boolean;
  updated_ts: number;
}

export interface Schedule {
  id: string;
  mode: Mode;
  steps: Step[];
  status: "running" | "paused" | "completed" | "ended";
  paused: boolean;
  started_ts: number;
  started_by: string | null;
  paused_ts: number | null;
  paused_ms: number;
  ended_ts: number | null;
  progress?: Progress | null;
}

/** A step being edited: inputs as typed. */
export interface DraftStep {
  key: string;
  direction: Direction;
  wet: boolean;
  speed: string;
  end: StepEnd;
  angle: string;
  hours: string;
  delay: string;
}

let keySeq = 0;
export const newKey = () => `s${Date.now().toString(36)}${(keySeq++).toString(36)}`;

export function blankStep(defaults: { speed: number; wet: boolean }, from?: DraftStep): DraftStep {
  return {
    key: newKey(),
    direction: from?.direction ?? "forward",
    wet: from?.wet ?? defaults.wet,
    speed: String(from ? from.speed : defaults.speed),
    end: from?.end ?? "angle",
    angle: "",
    hours: "",
    delay: "",
  };
}

const str = (n: number | null | undefined) => (n == null ? "" : String(n));

export function draftFromStep(step: Step): DraftStep {
  return {
    key: newKey(),
    direction: step.direction === "reverse" ? "reverse" : "forward",
    wet: Boolean(step.wet),
    speed: str(step.speed_percent),
    end: step.end === "time" ? "time" : "angle",
    angle: step.end === "time" ? "" : str(step.stop_angle_deg),
    hours: step.end === "time" ? str(step.run_hours) : "",
    delay: step.delay_min ? str(step.delay_min) : "",
  };
}

/** A typed number: null when blank, NaN when it isn't a number. */
export function parseNum(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

/** What's wrong with one step (empty when valid). */
export function stepErrors(d: DraftStep, maxHours = 0): string[] {
  const errors: string[] = [];
  const speed = parseNum(d.speed);
  if (speed == null || Number.isNaN(speed) || speed < 1 || speed > 100) errors.push("Speed must be 1–100 %");
  if (d.end === "angle") {
    const a = parseNum(d.angle);
    if (a != null && (Number.isNaN(a) || a < 0 || a > 360)) errors.push("Stop angle must be 0–360°");
    else if (a == null) errors.push("Choose a stop angle or a run time");
  } else {
    const h = parseNum(d.hours);
    if (h != null && Number.isNaN(h)) errors.push("Run time must be a number of hours");
    else if (h == null) errors.push("Choose a stop angle or a run time");
    else if (h <= 0) errors.push("Run time must be more than 0");
    else if (maxHours && h > maxHours) errors.push(`Run time can't be over the ${maxHours} h maximum`);
  }
  const delay = parseNum(d.delay);
  if (delay != null && Number.isNaN(delay)) errors.push("Start delay must be a number of minutes");
  else if (delay != null && delay < 0) errors.push("Start delay can't be negative");
  return errors;
}

export const lowerFirst = (s: string) => s.charAt(0).toLowerCase() + s.slice(1);

/** The step as sent to the processor (only called once it's valid). */
export function draftToStep(d: DraftStep): Step {
  return {
    direction: d.direction,
    wet: d.wet,
    speed_percent: Number(d.speed),
    end: d.end,
    stop_angle_deg: d.end === "angle" ? Number(d.angle) : null,
    run_hours: d.end === "time" ? Number(d.hours) : null,
    delay_min: parseNum(d.delay) ?? 0,
  };
}

// -- reading the tags ----------------------------------------------------------

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

export function asSchedule(v: unknown): Schedule | null {
  if (!isObj(v) || typeof v.id !== "string" || !Array.isArray(v.steps)) return null;
  return v as unknown as Schedule;
}

export function asHistory(v: unknown): Schedule[] {
  return Array.isArray(v) ? v.map(asSchedule).filter((s): s is Schedule => s !== null) : [];
}

// -- progress ------------------------------------------------------------------

export interface StepView {
  index: number;
  /** 0..1, or null when it can't be told yet (no angle reading). */
  fraction: number | null;
  waiting: boolean;
  remainingS: number | null;
  remainingDeg: number | null;
  estimated: boolean;
  /** Every step done: the processor will move it to Past Schedules on its next run. */
  finishing: boolean;
}

function pausedMsAt(s: Schedule, now: number): number {
  let total = s.paused_ms || 0;
  if (s.paused && s.paused_ts) total += Math.max(0, now - s.paused_ts);
  return total;
}

/**
 * Where the schedule is now. The processor keeps the step and the angle
 * travelled; time-based figures (delay, run time) are brought up to the second
 * here with the same rule it uses: time in the step, less time paused since it
 * began, first the start delay and then the run time.
 */
export function stepView(s: Schedule, now: number): StepView {
  const p = s.progress;
  const index = Math.min(p?.step_index ?? 0, s.steps.length);
  const base: StepView = {
    index,
    fraction: p?.fraction ?? null,
    waiting: Boolean(p?.waiting),
    remainingS: p?.remaining_s ?? null,
    remainingDeg: p?.remaining_deg ?? null,
    estimated: p?.estimated ?? true,
    finishing: index >= s.steps.length,
  };
  const step = s.steps[index];
  if (!p || !step || p.step_started_ts == null || p.paused_ms_at_step == null) return base;
  const at = s.paused && s.paused_ts ? s.paused_ts : now;
  const active = Math.max(0, at - p.step_started_ts - (pausedMsAt(s, at) - p.paused_ms_at_step));
  const delayMs = (step.delay_min ?? 0) * 60_000;
  if (active < delayMs) {
    return { ...base, waiting: true, fraction: 0, remainingS: Math.round((delayMs - active) / 1000), remainingDeg: null };
  }
  if (step.end === "time") {
    const runMs = (step.run_hours ?? 0) * 3_600_000;
    const ran = active - delayMs;
    return {
      ...base,
      waiting: false,
      fraction: runMs ? Math.min(1, ran / runMs) : 1,
      remainingS: Math.max(0, Math.round((runMs - ran) / 1000)),
      remainingDeg: null,
    };
  }
  return { ...base, waiting: false };
}

// -- words ---------------------------------------------------------------------

export function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

export const fmtNum = (n: number) => String(Math.round(n * 10) / 10);

export function fmtHours(h: number): string {
  return h < 1 ? `${Math.round(h * 60)} min` : `${fmtNum(h)} h`;
}

export function endText(step: { end: StepEnd; stop_angle_deg: number | null; run_hours: number | null }): string {
  return step.end === "time" ? `for ${fmtHours(step.run_hours ?? 0)}` : `to ${fmtNum(step.stop_angle_deg ?? 0)}°`;
}

export function fmtClock(ts: number, now = Date.now()): string {
  const d = new Date(ts);
  const time = d.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  if (new Date(now).toDateString() === d.toDateString()) return `today ${time}`;
  const yesterday = new Date(now - 86_400_000);
  if (yesterday.toDateString() === d.toDateString()) return `yesterday ${time}`;
  return `${d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" })} ${time}`;
}

export const modeLabel = (m: Mode) => (m === "simple" ? "Simple" : "Detailed");
