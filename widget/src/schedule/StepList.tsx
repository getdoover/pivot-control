import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { endText, fmtNum, parseNum, type DraftStep } from "./model";
import { AntiClockwise, Clockwise, cx, Droplet, DropletOff, Grip, X } from "./ui";

/** One step's settings in a line, from a draft (values as typed). */
export function DraftSummary({ d }: { d: DraftStep }) {
  const speed = parseNum(d.speed);
  const angle = parseNum(d.angle);
  const hours = parseNum(d.hours);
  const delay = parseNum(d.delay);
  const end =
    d.end === "angle"
      ? angle == null || Number.isNaN(angle)
        ? "no stop angle"
        : endText({ end: "angle", stop_angle_deg: angle, run_hours: null })
      : hours == null || Number.isNaN(hours)
        ? "no run time"
        : endText({ end: "time", stop_angle_deg: null, run_hours: hours });
  return (
    <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5">
      <span className="inline-flex items-center gap-1 font-medium">
        {d.direction === "forward" ? <Clockwise className="h-3.5 w-3.5" /> : <AntiClockwise className="h-3.5 w-3.5" />}
        {d.direction === "forward" ? "Forward" : "Reverse"}
      </span>
      <span className="text-muted-foreground">·</span>
      <span className="inline-flex items-center gap-1">
        {d.wet ? <Droplet className="h-3.5 w-3.5 text-sky-500" /> : <DropletOff className="h-3.5 w-3.5 text-muted-foreground" />}
        {d.wet ? "Wet" : "Dry"}
      </span>
      <span className="text-muted-foreground">·</span>
      <span>{speed == null || Number.isNaN(speed) ? "–" : fmtNum(speed)} %</span>
      <span className="text-muted-foreground">·</span>
      <span>{end}</span>
      {delay != null && !Number.isNaN(delay) && delay > 0 && <span className="text-muted-foreground">· after {fmtNum(delay)} min</span>}
    </span>
  );
}

/**
 * The steps built so far, in order. Click one to edit it, × to remove it, and
 * drag its handle (mouse or touch) to reorder. With the handle focused, the up
 * and down arrow keys move the step.
 */
export function StepList({
  steps,
  editingKey,
  errors,
  onSelect,
  onRemove,
  onMove,
}: {
  steps: DraftStep[];
  editingKey: string;
  errors: Record<string, string[]>;
  onSelect: (key: string) => void;
  onRemove: (key: string) => void;
  onMove: (from: number, to: number) => void;
}) {
  const rows = useRef<Map<string, HTMLLIElement>>(new Map());
  const [dragKey, setDragKey] = useState<string | null>(null);

  const indexAt = (y: number) => {
    let target = 0;
    steps.forEach((s, i) => {
      const r = rows.current.get(s.key)?.getBoundingClientRect();
      if (r && y > r.top + r.height / 2) target = i;
    });
    return target;
  };

  const onPointerDown = (e: PointerEvent<HTMLButtonElement>, key: string) => {
    if (e.button !== 0) return;
    e.preventDefault();
    e.currentTarget.setPointerCapture(e.pointerId);
    setDragKey(key);
  };
  const onPointerMove = (e: PointerEvent<HTMLButtonElement>) => {
    if (!dragKey) return;
    const from = steps.findIndex((s) => s.key === dragKey);
    const to = indexAt(e.clientY);
    if (from >= 0 && to !== from) onMove(from, to);
  };
  const endDrag = () => setDragKey(null);
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    if (e.key === "ArrowUp" && i > 0) {
      e.preventDefault();
      onMove(i, i - 1);
    } else if (e.key === "ArrowDown" && i < steps.length - 1) {
      e.preventDefault();
      onMove(i, i + 1);
    }
  };

  return (
    <ol className="flex max-h-60 flex-col gap-1.5 overflow-y-auto overscroll-contain p-0.5" aria-label="Steps">
      {steps.map((s, i) => {
        const errs = errors[s.key] ?? [];
        const editing = s.key === editingKey;
        return (
          <li
            key={s.key}
            ref={(el) => {
              if (el) rows.current.set(s.key, el);
              else rows.current.delete(s.key);
            }}
            className={cx(
              "flex items-stretch rounded-md border bg-background text-sm transition-shadow",
              errs.length ? "border-destructive bg-destructive/5" : editing ? "border-primary ring-1 ring-primary/40" : "border-border",
              dragKey === s.key && "relative z-10 shadow-lg ring-2 ring-ring/40",
            )}
          >
            <button
              aria-label={`Move step ${i + 1} (drag, or use the arrow keys)`}
              title="Drag to reorder"
              className="flex w-8 shrink-0 touch-none items-center justify-center rounded-l-md text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/60 active:cursor-grabbing"
              style={{ cursor: dragKey ? "grabbing" : "grab" }}
              onPointerDown={(e) => onPointerDown(e, s.key)}
              onPointerMove={onPointerMove}
              onPointerUp={endDrag}
              onPointerCancel={endDrag}
              onKeyDown={(e) => onKey(e, i)}
            >
              <Grip className="h-4 w-4" />
            </button>
            <button
              className="flex min-w-0 flex-1 items-start gap-2 py-2 pr-1 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
              onClick={() => onSelect(s.key)}
              aria-current={editing ? "step" : undefined}
            >
              <span
                className={cx(
                  "mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold tabular-nums",
                  errs.length ? "bg-destructive text-white" : editing ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                )}
              >
                {i + 1}
              </span>
              <span className="flex min-w-0 flex-col gap-0.5">
                <DraftSummary d={s} />
                {errs.map((m) => (
                  <span key={m} className="text-xs font-medium text-destructive">
                    {m}
                  </span>
                ))}
              </span>
            </button>
            {steps.length > 1 && (
              <button
                aria-label={`Remove step ${i + 1}`}
                title="Remove step"
                className="flex w-8 shrink-0 items-center justify-center rounded-r-md text-muted-foreground outline-none hover:text-destructive focus-visible:ring-2 focus-visible:ring-ring/60"
                onClick={() => onRemove(s.key)}
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </li>
        );
      })}
    </ol>
  );
}
