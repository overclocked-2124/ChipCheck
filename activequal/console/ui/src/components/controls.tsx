"use client";

// Form controls shared by every page: an accessible listbox select (Radix), a typed number field with steppers
// instead of browser spinners, and a tooltip. Styles live in controls.css.

import * as RSelect from "@radix-ui/react-select";
import * as RTooltip from "@radix-ui/react-tooltip";
import { CaretDown, Check, Minus, Plus } from "@phosphor-icons/react";
import { useId, type ReactNode } from "react";
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
