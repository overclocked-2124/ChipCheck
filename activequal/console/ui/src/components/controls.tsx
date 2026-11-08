"use client";

// Form controls shared by every page: an accessible listbox select (Radix), a typed number field with steppers
// instead of browser spinners, and a tooltip. Styles live in controls.css.

import * as RSelect from "@radix-ui/react-select";
import * as RPopover from "@radix-ui/react-popover";
import * as RTooltip from "@radix-ui/react-tooltip";
import { CalendarBlank, CaretDown, CaretLeft, CaretRight, Check, Minus, Plus } from "@phosphor-icons/react";
import { useId, useState, type ReactNode } from "react";
import { formatLocal, monthGrid, parseLocal } from "@/lib/datetime";
import { numberProblem, stepNumber, type NumberRule } from "@/lib/number";

export type Option = { value: string; label: ReactNode; hint?: ReactNode; disabled?: boolean };

// Radix Select refuses an item whose value is "", so an empty value travels as this sentinel.
const EMPTY = "__empty__";
const enc = (v: string) => (v === "" ? EMPTY : v);
const dec = (v: string) => (v === EMPTY ? "" : v);

export function Select({ value, onChange, options, label, ariaLabel, placeholder, compact, disabled, id }: {
  value: string; onChange: (v: string) => void; options: (Option | string)[]; label?: ReactNode; ariaLabel?: string;
  placeholder?: string; compact?: boolean; disabled?: boolean; id?: string;
}) {
  const auto = useId();
  const triggerId = id ?? auto;
  const opts = options.map(o => (typeof o === "string" ? { value: o, label: o } : o));
  return (
    <div className={`field${compact ? " compact" : ""}`}>
      {label ? <label htmlFor={triggerId}>{label}</label> : null}
      <RSelect.Root value={enc(value)} onValueChange={v => onChange(dec(v))} disabled={disabled}>
        <RSelect.Trigger id={triggerId} className="select-trigger" aria-label={ariaLabel}>
          <span className="select-value"><RSelect.Value placeholder={placeholder ?? "Choose…"} /></span>
          <RSelect.Icon className="select-caret"><CaretDown size={14} weight="bold" /></RSelect.Icon>
        </RSelect.Trigger>
        <RSelect.Portal>
          <RSelect.Content className="select-content" position="popper" sideOffset={6} collisionPadding={12}>
            <RSelect.Viewport className="select-viewport">
              {opts.map(o => (
                <RSelect.Item key={o.value} value={enc(o.value)} className="select-item" disabled={o.disabled}>
                  <RSelect.ItemText>{o.label}</RSelect.ItemText>
                  {o.hint ? <span className="select-hint">{o.hint}</span> : null}
                  <RSelect.ItemIndicator className="select-check"><Check size={14} weight="bold" /></RSelect.ItemIndicator>
                </RSelect.Item>
              ))}
            </RSelect.Viewport>
          </RSelect.Content>
        </RSelect.Portal>
      </RSelect.Root>
    </div>
  );
}

/** Text the user types stays as typed; arrow keys and the − / + buttons step it. The caller blocks submit on `numberProblem`. */
export function NumberField({ label, value, onChange, step = 1, unit, hint, rule = {}, id, wide }: {
  label: ReactNode; value: string; onChange: (v: string) => void; step?: number; unit?: string; hint?: ReactNode;
  rule?: NumberRule; id?: string; wide?: boolean;
}) {
  const auto = useId();
  const inputId = id ?? auto;
  const problem = numberProblem(value, rule);
  const shown = value.trim() !== "" || rule.required === false ? problem : null;
  const bump = (d: 1 | -1) => onChange(stepNumber(value, d, step, rule));
  const atMin = rule.min !== undefined && Number(value) <= rule.min;
  const atMax = rule.max !== undefined && Number(value) >= rule.max;
  return (
    <div className={`field${wide ? " wide" : ""}`}>
      <label htmlFor={inputId}>{label}</label>
      <div className={`numbox${shown ? " invalid" : ""}`}>
        <button type="button" className="step" tabIndex={-1} aria-label="Decrease" disabled={atMin} onClick={() => bump(-1)}><Minus size={12} weight="bold" /></button>
        <input id={inputId} type="text" inputMode={rule.integer ? "numeric" : "decimal"} autoComplete="off" spellCheck={false}
          value={value} aria-invalid={!!shown} aria-describedby={shown ? `${inputId}-err` : hint ? `${inputId}-hint` : undefined}
          onChange={e => onChange(e.target.value)}
          onKeyDown={e => { if (e.key === "ArrowUp" || e.key === "ArrowDown") { e.preventDefault(); bump(e.key === "ArrowUp" ? 1 : -1); } }} />
        {unit ? <span className="unit">{unit}</span> : null}
        <button type="button" className="step" tabIndex={-1} aria-label="Increase" disabled={atMax} onClick={() => bump(1)}><Plus size={12} weight="bold" /></button>
      </div>
      {shown ? <small className="field-error" id={`${inputId}-err`}>{shown}</small>
        : hint ? <small className="field-hint" id={`${inputId}-hint`}>{hint}</small> : null}
    </div>
  );
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <RTooltip.Provider delayDuration={250} skipDelayDuration={100}>{children}</RTooltip.Provider>;
}

/** Hover or focus tooltip. `children` must be a single focusable element (or one that accepts a ref). */
export function Tip({ content, children }: { content: ReactNode; children: ReactNode }) {
  if (!content) return <>{children}</>;
  return (
    <RTooltip.Root>
      <RTooltip.Trigger asChild>{children}</RTooltip.Trigger>
      <RTooltip.Portal>
        <RTooltip.Content className="tip" sideOffset={6} collisionPadding={12}>{content}<RTooltip.Arrow className="tip-arrow" /></RTooltip.Content>
      </RTooltip.Portal>
    </RTooltip.Root>
  );
}

// ---------------------------------------------------------------- date and time

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
const same = (a: Date, b: Date) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();

/** Typed or picked local date and time. Replaces the browser's dark native picker, which cannot be themed. */
export function DateTimeField({ label, value, onChange, presets }: {
  label: ReactNode; value: string; onChange: (v: string) => void; presets?: { label: string; days: number }[];
}) {
  const auto = useId();
  const parsed = parseLocal(value);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState(() => parsed ?? new Date());
  const today = new Date();
  const base = parsed ?? new Date(today.getFullYear(), today.getMonth(), today.getDate(), 12, 0);
  const pick = (d: Date) => onChange(formatLocal(new Date(d.getFullYear(), d.getMonth(), d.getDate(), base.getHours(), base.getMinutes())));
  const setTime = (h: number, m: number) => onChange(formatLocal(new Date(base.getFullYear(), base.getMonth(), base.getDate(), h, m)));
  const bad = value.trim() !== "" && !parsed;
  return (
    <div className="field">
      <label htmlFor={auto}>{label}</label>
      <RPopover.Root open={open} onOpenChange={o => { setOpen(o); if (o) setView(parsed ?? new Date()); }}>
        <RPopover.Anchor asChild>
          <div className={`numbox${bad ? " invalid" : ""}`}>
            <input id={auto} type="text" value={value} placeholder="YYYY-MM-DDTHH:mm" autoComplete="off" spellCheck={false}
              aria-invalid={bad} style={{ textAlign: "left", paddingLeft: 13 }} onChange={e => onChange(e.target.value)} />
            <RPopover.Trigger asChild>
              <button type="button" className="step" aria-label="Open the calendar" style={{ borderLeft: "1px solid var(--line-soft)" }}><CalendarBlank size={16} /></button>
            </RPopover.Trigger>
          </div>
        </RPopover.Anchor>
        {bad ? <small className="field-error">Use YYYY-MM-DDTHH:mm, for example 2026-12-31T18:00</small> : null}
        <RPopover.Portal>
          <RPopover.Content className="select-content datepop" side="top" sideOffset={6} align="end" collisionPadding={12}>
            <div className="cal-head">
              <button type="button" className="step" aria-label="Previous month" onClick={() => setView(new Date(view.getFullYear(), view.getMonth() - 1, 1))}><CaretLeft size={14} weight="bold" /></button>
              <strong>{MONTHS[view.getMonth()]} {view.getFullYear()}</strong>
              <button type="button" className="step" aria-label="Next month" onClick={() => setView(new Date(view.getFullYear(), view.getMonth() + 1, 1))}><CaretRight size={14} weight="bold" /></button>
            </div>
            <div className="cal-grid" role="grid">
              {["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"].map(d => <span key={d} className="cal-dow">{d}</span>)}
              {monthGrid(view.getFullYear(), view.getMonth()).flat().map(d => (
                <button type="button" key={d.getTime()} className={`cal-day${d.getMonth() !== view.getMonth() ? " out" : ""}${parsed && same(d, parsed) ? " sel" : ""}${same(d, today) ? " today" : ""}`}
                  onClick={() => pick(d)}>{d.getDate()}</button>
              ))}
            </div>
            <div className="cal-time">
              <span>Time</span>
              <input aria-label="Hour" inputMode="numeric" value={pad2(base.getHours())} onChange={e => { const h = Number(e.target.value.replace(/\D/g, "").slice(-2)); if (h < 24) setTime(h, base.getMinutes()); }} />
              <b>:</b>
              <input aria-label="Minute" inputMode="numeric" value={pad2(base.getMinutes())} onChange={e => { const m = Number(e.target.value.replace(/\D/g, "").slice(-2)); if (m < 60) setTime(base.getHours(), m); }} />
            </div>
            <div className="cal-foot">
              {(presets ?? []).map(p => <button type="button" key={p.label} className="secondary" onClick={() => { const d = new Date(); d.setDate(d.getDate() + p.days); onChange(formatLocal(new Date(d.getFullYear(), d.getMonth(), d.getDate(), 18, 0))); setOpen(false); }}>{p.label}</button>)}
              <button type="button" className="text" onClick={() => { onChange(""); setOpen(false); }}>Clear</button>
              <button type="button" onClick={() => setOpen(false)}>Done</button>
            </div>
          </RPopover.Content>
        </RPopover.Portal>
      </RPopover.Root>
    </div>
  );
}
const pad2 = (n: number) => String(n).padStart(2, "0");
