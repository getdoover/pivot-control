import "./schedule/schedule.css";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";

import RemoteComponentWrapper from "customer_site/RemoteComponentWrapper";
import { useRemoteParams } from "customer_site/useRemoteParams";
import { useAgentChannel, useDooverClient } from "doover-js/react";

import {
  asHistory,
  asSchedule,
  blankStep,
  draftFromStep,
  draftToStep,
  endText,
  fmtClock,
  fmtDuration,
  fmtNum,
  lowerFirst,
  modeLabel,
  parseNum,
  stepErrors,
  stepView,
  type DraftStep,
  type Mode,
  type Schedule,
  type Step,
  type StepView,
} from "./schedule/model";
import { callRpc, type Actor } from "./schedule/rpc";
import { DraftSummary, StepList } from "./schedule/StepList";
import {
  AntiClockwise,
  Banner,
  Button,
  Check,
  ChevronLeft,
  Clockwise,
  cx,
  Droplet,
  DropletOff,
  Field,
  History,
  ListSteps,
  NumberInput,
  Pause,
  Play,
  Plus,
  Segmented,
  Target,
} from "./schedule/ui";

interface UiElement {
  app_key?: string;
  [key: string]: unknown;
}

interface AppConfig {
  default_speed?: number | null;
  simple_wet?: boolean | null;
  max_run_hours?: number | null;
}

type Tags = Record<string, Record<string, unknown>>;
type View = "idle" | "menu" | "simple" | "detailed" | "past";
type Action = "start" | "pause" | "resume" | "end";

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

function useNow(ms = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

// -- running schedule ------------------------------------------------------------

function StepLine({ step }: { step: Step }) {
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
      <span className="inline-flex items-center gap-1 font-medium">
        {step.direction === "reverse" ? <AntiClockwise className="h-3.5 w-3.5" /> : <Clockwise className="h-3.5 w-3.5" />}
        {step.direction === "reverse" ? "Reverse" : "Forward"}
      </span>
      <span className="text-muted-foreground">·</span>
      <span className="inline-flex items-center gap-1">
        {step.wet ? <Droplet className="h-3.5 w-3.5 text-sky-500" /> : <DropletOff className="h-3.5 w-3.5 text-muted-foreground" />}
        {step.wet ? "Wet" : "Dry"}
      </span>
      <span className="text-muted-foreground">·</span>
      <span>{fmtNum(step.speed_percent)} %</span>
      <span className="text-muted-foreground">·</span>
      <span>{endText(step)}</span>
      {step.delay_min ? <span className="text-muted-foreground">· after {fmtNum(step.delay_min)} min</span> : null}
    </span>
  );
}

function progressCaption(step: Step, v: StepView, angle: number | null): string {
  if (v.waiting) return v.remainingS != null ? `Start delay · starts in ${fmtDuration(v.remainingS)}` : "Start delay";
  if (step.end === "time") return v.remainingS != null ? `${fmtDuration(v.remainingS)} left` : "Running";
  if (v.remainingDeg == null) return "Waiting for an angle reading";
  const at = angle != null ? ` · now at ${Math.round(angle)}°` : "";
  return `${fmtNum(v.remainingDeg)}° to go${at}`;
}

function ActiveSchedule({
  schedule,
  now,
  angle,
  busy,
  error,
  onAction,
}: {
  schedule: Schedule;
  now: number;
  angle: number | null;
  busy: Action | null;
  error: string | null;
  onAction: (a: Action) => void;
}) {
  const [confirmEnd, setConfirmEnd] = useState(false);
  const v = stepView(schedule, now);
  const paused = schedule.paused;
  const n = schedule.steps.length;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={cx(
            "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold",
            paused ? "bg-amber-500/15 text-amber-700 dark:text-amber-400" : "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400",
          )}
        >
          <span className={cx("h-1.5 w-1.5 rounded-full", paused ? "bg-amber-500" : "animate-pulse bg-emerald-500")} />
          {paused ? "Paused" : v.finishing ? "Finishing" : "Running"}
        </span>
        <span className="text-sm font-semibold">{modeLabel(schedule.mode)} schedule</span>
        {v.estimated && (
          <span
            className="rounded border border-border px-1.5 py-px text-[11px] text-muted-foreground"
            title="Progress worked out from the pivot's angle and the time elapsed, until the controller reports its own"
          >
            estimated
          </span>
        )}
      </div>
      <div className="text-xs text-muted-foreground">
        Started {fmtClock(schedule.started_ts, now)}
        {schedule.started_by ? ` by ${schedule.started_by}` : ""}
        {n > 1 && !v.finishing ? ` · step ${v.index + 1} of ${n}` : ""}
        {paused && schedule.paused_ts ? ` · paused ${fmtClock(schedule.paused_ts, now)}` : ""}
      </div>

      <ol className="flex max-h-72 flex-col gap-1.5 overflow-y-auto overscroll-contain" aria-label="Schedule steps">
        {schedule.steps.map((step, i) => {
          const done = i < v.index;
          const current = i === v.index;
          const pct = current && v.fraction != null ? Math.round(v.fraction * 100) : null;
          return (
            <li
              key={i}
              aria-current={current ? "step" : undefined}
              className={cx(
                "flex gap-2.5 rounded-md border px-3 py-2 text-sm",
                current ? (paused ? "border-amber-500/50 bg-amber-500/5" : "border-primary/50 bg-primary/5") : "border-border",
                done && "opacity-60",
              )}
            >
              <span
                className={cx(
                  "mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums",
                  done ? "bg-emerald-500 text-white" : current ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                )}
              >
                {done ? <Check className="h-3 w-3" strokeWidth={3} /> : i + 1}
              </span>
              <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <StepLine step={step} />
                {current && (
                  <>
                    <div
                      className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={pct ?? undefined}
                    >
                      <div
                        className={cx("h-full rounded-full transition-[width] duration-700", paused ? "bg-amber-500" : v.waiting ? "bg-muted-foreground/40" : "bg-primary")}
                        style={{ width: `${pct ?? 0}%` }}
                      />
                    </div>
                    <div className="flex flex-wrap justify-between gap-x-3 text-xs text-muted-foreground">
                      <span>{paused ? `Paused · ${progressCaption(step, v, angle)}` : progressCaption(step, v, angle)}</span>
                      {pct != null && !v.waiting && <span className="tabular-nums">{pct} %</span>}
                    </div>
                  </>
                )}
                {done && <span className="text-xs text-muted-foreground">Done</span>}
              </div>
            </li>
          );
        })}
      </ol>
      {v.finishing && <Banner tone="info">Every step is done. The schedule moves to Past Schedules shortly.</Banner>}

      {error && <Banner>{error}</Banner>}

      {confirmEnd ? (
        <div className="flex flex-col gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-3">
          <span className="text-sm">End this schedule now? The pivot stops at the controller and the schedule moves to Past Schedules.</span>
          <div className="flex flex-wrap justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setConfirmEnd(false)} disabled={busy === "end"}>
              Keep running
            </Button>
            <Button size="sm" variant="destructive" busy={busy === "end"} onClick={() => onAction("end")}>
              End schedule
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {paused ? (
            <Button variant="primary" busy={busy === "resume"} disabled={busy !== null} onClick={() => onAction("resume")}>
              {busy !== "resume" && <Play className="h-4 w-4" />}
              {busy === "resume" ? "Resuming…" : "Resume"}
            </Button>
          ) : (
            <Button variant="outline" busy={busy === "pause"} disabled={busy !== null || v.finishing} onClick={() => onAction("pause")}>
              {busy !== "pause" && <Pause className="h-4 w-4" />}
              {busy === "pause" ? "Pausing…" : "Pause"}
            </Button>
          )}
          <Button size="sm" variant="ghost" className="text-muted-foreground hover:text-destructive" disabled={busy !== null} onClick={() => setConfirmEnd(true)}>
            End schedule
          </Button>
        </div>
      )}
    </div>
  );
}

// -- editors ---------------------------------------------------------------------

function StepEditor({
  draft,
  onChange,
  errors,
  angle,
  title,
}: {
  draft: DraftStep;
  onChange: (d: DraftStep) => void;
  errors: string[];
  angle: number | null;
  title: string;
}) {
  const set = (patch: Partial<DraftStep>) => onChange({ ...draft, ...patch });
  const has = (word: string) => errors.some((e) => e.toLowerCase().includes(word));
  const id = draft.key;
  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-muted/20 p-3">
      <div className="text-sm font-semibold">{title}</div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Direction">
          <Segmented
            label="Direction"
            value={draft.direction}
            onChange={(direction) => set({ direction })}
            options={[
              { value: "forward", label: <><Clockwise className="h-3.5 w-3.5" />Forward</> },
              { value: "reverse", label: <><AntiClockwise className="h-3.5 w-3.5" />Reverse</> },
            ]}
          />
        </Field>
        <Field label="Water">
          <Segmented
            label="Water"
            value={draft.wet ? "wet" : "dry"}
            onChange={(w) => set({ wet: w === "wet" })}
            options={[
              { value: "wet", label: <><Droplet className="h-3.5 w-3.5" />Wet</> },
              { value: "dry", label: <><DropletOff className="h-3.5 w-3.5" />Dry</> },
            ]}
          />
        </Field>
        <Field label="Speed" htmlFor={`${id}-speed`}>
          <NumberInput id={`${id}-speed`} value={draft.speed} onChange={(speed) => set({ speed })} unit="%" invalid={has("speed")} />
        </Field>
        <Field label="Start delay (optional)" htmlFor={`${id}-delay`}>
          <NumberInput id={`${id}-delay`} value={draft.delay} onChange={(delay) => set({ delay })} unit="min" placeholder="0" invalid={has("delay")} />
        </Field>
        <Field label="Ends">
          <Segmented
            label="Ends"
            value={draft.end}
            onChange={(end) => set({ end })}
            options={[
              { value: "angle", label: "At an angle" },
              { value: "time", label: "After a time" },
            ]}
          />
        </Field>
        {draft.end === "angle" ? (
          <Field label="Stop angle" htmlFor={`${id}-angle`} hint={angle != null ? `The pivot is at ${Math.round(angle)}° now` : undefined}>
            <NumberInput
              id={`${id}-angle`}
              value={draft.angle}
              onChange={(a) => set({ angle: a })}
              unit="°"
              placeholder="0–360"
              invalid={has("angle") || has("choose")}
            />
          </Field>
        ) : (
          <Field label="Run time" htmlFor={`${id}-hours`}>
            <NumberInput
              id={`${id}-hours`}
              value={draft.hours}
              onChange={(hours) => set({ hours })}
              unit="h"
              placeholder="e.g. 2.5"
              invalid={has("run time") || has("choose")}
            />
          </Field>
        )}
      </div>
      {errors.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {errors.map((e) => (
            <li key={e} className="text-xs font-medium text-destructive">
              {e}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SimpleEditor({
  draft,
  onChange,
  errors,
  angle,
  defaults,
}: {
  draft: DraftStep;
  onChange: (d: DraftStep) => void;
  errors: string[];
  angle: number | null;
  defaults: { speed: number; wet: boolean };
}) {
  const id = draft.key;
  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <Field label="Direction">
          <Segmented
            label="Direction"
            value={draft.direction}
            onChange={(direction) => onChange({ ...draft, direction })}
            options={[
              { value: "forward", label: <><Clockwise className="h-3.5 w-3.5" />Forward</> },
              { value: "reverse", label: <><AntiClockwise className="h-3.5 w-3.5" />Reverse</> },
            ]}
          />
        </Field>
        <Field label="Stop angle" htmlFor={`${id}-angle`} hint={angle != null ? `The pivot is at ${Math.round(angle)}° now` : undefined}>
          <NumberInput
            id={`${id}-angle`}
            value={draft.angle}
            onChange={(a) => onChange({ ...draft, angle: a })}
            unit="°"
            placeholder="0–360"
            invalid={errors.length > 0}
          />
        </Field>
      </div>
      <div className="text-xs text-muted-foreground">
        Runs {defaults.wet ? "wet" : "dry"} at {fmtNum(defaults.speed)} % (this pivot's defaults). Use Detailed for anything else.
      </div>
      {errors.map((e) => (
        <div key={e} className="text-xs font-medium text-destructive">
          {e}
        </div>
      ))}
    </div>
  );
}

// -- past schedules ----------------------------------------------------------------

function PastSchedules({ history, now, onPick }: { history: Schedule[]; now: number; onPick: (s: Schedule) => void }) {
  if (!history.length) return <Banner tone="info">No past schedules yet. They appear here once a schedule finishes or is ended.</Banner>;
  return (
    <ul className="flex max-h-96 flex-col gap-2 overflow-y-auto overscroll-contain p-0.5" aria-label="Past schedules">
      {history.map((s) => (
        <li key={s.id}>
          <button
            onClick={() => onPick(s)}
            className="flex w-full flex-col gap-1.5 rounded-md border border-border bg-background p-3 text-left text-sm outline-none transition-colors hover:border-primary/60 hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-semibold">
                {modeLabel(s.mode)} · {s.steps.length} step{s.steps.length === 1 ? "" : "s"}
              </span>
              <span
                className={cx(
                  "rounded-full px-2 py-px text-[11px] font-medium",
                  s.status === "completed" ? "bg-emerald-500/15 text-emerald-700 dark:text-emerald-400" : "bg-muted text-muted-foreground",
                )}
              >
                {s.status === "completed" ? "Completed" : "Ended early"}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">{fmtClock(s.started_ts, now)}</span>
            </span>
            <ol className="flex flex-col gap-0.5 text-xs">
              {s.steps.map((step, i) => (
                <li key={i} className="flex gap-1.5">
                  <span className="w-4 shrink-0 text-right tabular-nums text-muted-foreground">{i + 1}.</span>
                  <StepLine step={step} />
                </li>
              ))}
            </ol>
            <span className="text-xs font-medium text-primary">Use this schedule →</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

// -- the widget ------------------------------------------------------------------

function Card({ children }: { children: ReactNode }) {
  return <div className="psw flex w-full flex-col gap-3 text-sm text-foreground">{children}</div>;
}

function Header({ title, onBack, right }: { title: string; onBack?: () => void; right?: ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      {onBack && (
        <Button size="sm" variant="ghost" className="-ml-2 px-2" onClick={onBack} aria-label="Back">
          <ChevronLeft className="h-4 w-4" />
        </Button>
      )}
      <span className="text-sm font-semibold">{title}</span>
      <span className="flex-1" />
      {right}
    </div>
  );
}

function ScheduleInner({ uiElement }: { uiElement?: UiElement }) {
  const params = useRemoteParams();
  const agentId = params.agentId;
  const appKey = uiElement?.app_key;
  const client = useDooverClient();
  const now = useNow();

  const { data: depCfg } = useAgentChannel<{ applications?: Record<string, AppConfig> }>(agentId, "deployment_config");
  const cfg: AppConfig = (appKey ? depCfg?.applications?.[appKey] : undefined) ?? {};
  const defaults = useMemo(
    () => ({
      speed: Math.min(100, Math.max(1, num(cfg.default_speed) ?? 50)),
      wet: cfg.simple_wet !== false,
    }),
    [cfg.default_speed, cfg.simple_wet],
  );
  const maxHours = num(cfg.max_run_hours) ?? 0;

  const { data: tagValues, isLoading } = useAgentChannel<Tags>(agentId, "tag_values");
  const own = (appKey && tagValues?.[appKey]) || {};
  const active = asSchedule(own.schedule_active);
  const history = asHistory(own.schedule_history);
  const angle = num(own.angle_deg);

  const me = useQuery({ queryKey: ["pivot-control", "me"], queryFn: () => client.users.getMe(), staleTime: Infinity, retry: 1 });
  const actor = useMemo<Actor | undefined>(() => {
    const u = me.data as Record<string, unknown> | undefined;
    if (!u) return undefined;
    const full = [u.first_name, u.last_name].filter((x) => typeof x === "string" && x).join(" ");
    return { id: String(u.id), name: full || String(u.username ?? u.email ?? u.id), email: String(u.email ?? "") };
  }, [me.data]);

  // Editor state.
  const [view, setView] = useState<View>("idle");
  const [steps, setSteps] = useState<DraftStep[]>(() => [blankStep(defaults)]);
  const [editingKey, setEditingKey] = useState<string>(() => steps[0].key);
  const [errors, setErrors] = useState<Record<string, string[]>>({});
  const [summary, setSummary] = useState<string | null>(null);

  // A request in flight, then held until the tags show its effect (or 20 s pass).
  const [busy, setBusy] = useState<{ action: Action; id?: string; at: number } | null>(null);
  const [rpcError, setRpcError] = useState<string | null>(null);

  useEffect(() => {
    if (!busy || busy.at === 0) return;
    const settled =
      (busy.action === "start" && active && active.id === busy.id) ||
      (busy.action === "pause" && active?.paused) ||
      (busy.action === "resume" && active && !active.paused) ||
      (busy.action === "end" && (!active || active.id !== busy.id));
    if (settled || now - busy.at > 20_000) setBusy(null);
  }, [busy, active, now]);

  const resetEditor = useCallback(
    (next: View, from?: Step[]) => {
      const drafts = from?.length ? from.map(draftFromStep) : [blankStep(defaults)];
      setSteps(drafts);
      setEditingKey(drafts[0].key);
      setErrors({});
      setSummary(null);
      setRpcError(null);
      setView(next);
    },
    [defaults],
  );

  const run = async (action: Action, request: Record<string, unknown>, label: string) => {
    if (!agentId || !appKey) return false;
    setRpcError(null);
    setBusy({ action, id: (request.schedule_id as string) ?? undefined, at: 0 });
    const res = await callRpc(client, agentId, appKey, `schedule_${action}`, request, label, actor);
    if (!res.ok) {
      setBusy(null);
      setRpcError(res.error);
      return false;
    }
    setBusy({ action, id: String(res.response.schedule_id ?? request.schedule_id ?? ""), at: Date.now() });
    return true;
  };

  const go = async (mode: Mode) => {
    const list = mode === "simple" ? steps.slice(0, 1).map((s) => ({ ...s, speed: String(defaults.speed), end: "angle" as const })) : steps;
    const found: Record<string, string[]> = {};
    const lines: string[] = [];
    list.forEach((s, i) => {
      const errs = stepErrors(s, maxHours);
      if (errs.length) {
        found[s.key] = mode === "simple" ? errs : errs.map((e) => `Step ${i + 1}: ${lowerFirst(e)}`);
        lines.push(...found[s.key]);
      }
    });
    setErrors(found);
    if (lines.length) {
      setSummary(mode === "simple" ? null : `Fix ${Object.keys(found).length === 1 ? "the highlighted step" : "the highlighted steps"} before starting.`);
      const firstBad = list.find((s) => found[s.key]);
      if (firstBad) setEditingKey(firstBad.key);
      return;
    }
    setSummary(null);
    const payload = {
      mode,
      steps: list.map((s) => {
        const step = draftToStep(s);
        return mode === "simple" ? { direction: step.direction, stop_angle_deg: step.stop_angle_deg } : step;
      }),
    };
    const ok = await run("start", payload, "Start schedule");
    if (ok) resetEditor("idle");
  };

  const updateStep = (d: DraftStep) => {
    setSteps((list) => list.map((s) => (s.key === d.key ? d : s)));
    if (errors[d.key]) setErrors(({ [d.key]: _drop, ...rest }) => rest);
  };

  if (!agentId || !appKey) return <Card><Banner tone="info">The schedule is missing its device or app key.</Banner></Card>;
  if (isLoading && !tagValues) return <Card><span className="text-muted-foreground">Loading schedule…</span></Card>;

  // A schedule is running (or paused): it fills the panel.
  if (active) {
    return (
      <Card>
        <ActiveSchedule
          schedule={active}
          now={now}
          angle={angle}
          busy={busy && busy.action !== "start" ? busy.action : null}
          error={rpcError}
          onAction={(a) => void run(a, { schedule_id: active.id }, a === "pause" ? "Pause schedule" : a === "resume" ? "Resume schedule" : "End schedule")}
        />
      </Card>
    );
  }

  if (busy?.action === "start") {
    return (
      <Card>
        <div className="flex items-center gap-2 py-6 text-muted-foreground">
          <span className="h-2 w-2 animate-pulse rounded-full bg-primary" /> Starting the schedule…
        </div>
      </Card>
    );
  }

  if (view === "simple") {
    const d = steps[0];
    return (
      <Card>
        <Header title="Simple schedule" onBack={() => resetEditor("menu")} />
        <SimpleEditor draft={d} onChange={updateStep} errors={errors[d.key] ?? []} angle={angle} defaults={defaults} />
        {rpcError && <Banner>{rpcError}</Banner>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => resetEditor("idle")}>
            Cancel
          </Button>
          <Button variant="primary" busy={busy !== null} onClick={() => void go("simple")}>
            <Play className="h-4 w-4" />
            Go
          </Button>
        </div>
      </Card>
    );
  }

  if (view === "detailed") {
    const index = Math.max(0, steps.findIndex((s) => s.key === editingKey));
    const editing = steps[index];
    return (
      <Card>
        <Header title="Detailed schedule" onBack={() => resetEditor("menu")} right={<span className="text-xs text-muted-foreground">{steps.length} step{steps.length === 1 ? "" : "s"}</span>} />
        {steps.length > 1 && (
          <StepList
            steps={steps}
            editingKey={editing.key}
            errors={errors}
            onSelect={setEditingKey}
            onRemove={(key) => {
              setSteps((list) => {
                const next = list.filter((s) => s.key !== key);
                if (key === editingKey) setEditingKey(next[Math.min(index, next.length - 1)].key);
                return next;
              });
              setErrors(({ [key]: _drop, ...rest }) => rest);
            }}
            onMove={(from, to) =>
              setSteps((list) => {
                const next = [...list];
                const [moved] = next.splice(from, 1);
                next.splice(to, 0, moved);
                return next;
              })
            }
          />
        )}
        <StepEditor
          key={editing.key}
          draft={editing}
          onChange={updateStep}
          errors={errors[editing.key] ?? []}
          angle={angle}
          title={`Step ${index + 1}`}
        />
        {summary && <Banner>{summary}</Banner>}
        {rpcError && <Banner>{rpcError}</Banner>}
        <div className="flex flex-wrap items-center justify-end gap-2">
          <Button variant="ghost" className="mr-auto" onClick={() => resetEditor("idle")}>
            Cancel
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              const fresh = blankStep(defaults, steps[steps.length - 1]);
              setSteps((list) => [...list, fresh]);
              setEditingKey(fresh.key);
            }}
          >
            <Plus className="h-4 w-4" />
            Add Step
          </Button>
          <Button variant="primary" busy={busy !== null} onClick={() => void go("detailed")}>
            <Play className="h-4 w-4" />
            Go
          </Button>
        </div>
      </Card>
    );
  }

  if (view === "past") {
    return (
      <Card>
        <Header title="Past schedules" onBack={() => setView("menu")} right={<span className="text-xs text-muted-foreground">Latest {history.length} of 5</span>} />
        <PastSchedules history={history} now={now} onPick={(s) => resetEditor(s.mode === "simple" ? "simple" : "detailed", s.steps)} />
      </Card>
    );
  }

  // Nothing running.
  const status = typeof own.status === "string" ? own.status : null;
  const heading = typeof own.heading === "string" ? own.heading : null;
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="text-sm font-semibold">No schedule running</span>
          <span className="text-xs text-muted-foreground">
            {[status && `Pivot: ${status}`, heading].filter(Boolean).join(" · ") || "Plan the pivot's next run as a schedule."}
          </span>
        </div>
        {view !== "menu" && (
          <Button variant="primary" onClick={() => setView("menu")}>
            <Plus className="h-4 w-4" />
            Create Schedule
          </Button>
        )}
      </div>
      {view === "menu" && (
        <>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {(
              [
                { key: "simple", icon: <Target className="h-5 w-5" />, title: "Simple", text: "One run in a direction, to a stop angle." },
                { key: "detailed", icon: <ListSteps className="h-5 w-5" />, title: "Detailed", text: "Steps with their own direction, water, speed and end." },
                {
                  key: "past",
                  icon: <History className="h-5 w-5" />,
                  title: "Past Schedules",
                  text: history.length ? `Start from one of the last ${history.length}.` : "Start from a recent schedule.",
                },
              ] as const
            ).map((o) => (
              <button
                key={o.key}
                onClick={() => (o.key === "past" ? setView("past") : resetEditor(o.key))}
                className="flex flex-col items-start gap-1 rounded-lg border border-border bg-background p-3 text-left outline-none transition-colors hover:border-primary/60 hover:bg-accent/40 focus-visible:ring-2 focus-visible:ring-ring/60"
              >
                <span className="text-primary">{o.icon}</span>
                <span className="text-sm font-semibold">{o.title}</span>
                <span className="text-xs text-muted-foreground">{o.text}</span>
              </button>
            ))}
          </div>
          <div className="flex justify-end">
            <Button size="sm" variant="ghost" onClick={() => setView("idle")}>
              Cancel
            </Button>
          </div>
        </>
      )}
      {rpcError && <Banner>{rpcError}</Banner>}
    </Card>
  );
}

export default function ScheduleWidget(props: { uiElement?: UiElement }) {
  return (
    <RemoteComponentWrapper>
      <ScheduleInner {...props} />
    </RemoteComponentWrapper>
  );
}
