"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MotionConfig, motion } from "motion/react";
import { useEffect, useState, type ReactNode } from "react";
import { useLoad, useNow, useReachability } from "@/components/api";
import { TooltipProvider } from "@/components/controls";
import { actorCookie, readActor } from "@/lib/client";
import { connectionBanner } from "@/lib/live";
import type { CampaignView } from "@/lib/types";

const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Campaigns" },
  { href: "/campaigns/new", label: "New campaign" },
  { href: "/contracts", label: "Contracts" },
  { href: "/fixtures", label: "Fixtures" },
  { href: "/compare", label: "Compare" },
];

/** Which sidebar entry a path belongs to. Campaign pages (live, results) sit under Campaigns. */
function section(path: string): string {
  if (path === "/campaigns/new") return "/campaigns/new";
  for (const href of ["/contracts", "/fixtures", "/compare"]) if (path.startsWith(href)) return href;
  return "/";
}

/** Upper-case breadcrumb from the path: CAMPAIGNS / 01A1BC39-33A / RESULTS. Ids are shortened. */
function Crumbs({ path }: { path: string }) {
  const parts = path.split("/").filter(Boolean);
  const head = NAV.find(n => n.href === section(path))?.label ?? "Campaigns";
  const rest = (path === "/campaigns/new" ? [] : parts.slice(1)).map(p => decodeURIComponent(p));
  return (
    <nav className="crumbs" aria-label="Breadcrumb">
      <Link href={section(path)}>{head}</Link>
      {rest.map((p, i) => <span key={i}> / {p.length > 14 ? p.slice(0, 12) : p}</span>)}
    </nav>
  );
}

function NameField() {
  const [name, setName] = useState("");
  const [saved, setSaved] = useState("");
  const [invalid, setInvalid] = useState(false);
  useEffect(() => { const n = readActor(document.cookie); setName(n); setSaved(n); }, []);
  function save() {
    const cookie = actorCookie(name);
    if (!cookie) { setInvalid(true); return; }
    document.cookie = cookie; setSaved(name.trim()); setInvalid(false);
  }
  return (
    <form className="namefield" onSubmit={e => { e.preventDefault(); save(); }}>
      <label><span>Name</span>
        <input value={name} onChange={e => { setName(e.target.value); setInvalid(false); }} onBlur={() => { if (name.trim() && name.trim() !== saved) save(); }}
          placeholder="recorded with every action" autoComplete="name" aria-invalid={invalid} maxLength={60} />
      </label>
      {invalid ? <span className="bad-text" role="alert">Letters, digits, space . _ - only</span>
        : saved ? <span className="who">Recorded as {saved}</span> : <span className="bad-text">Enter your name to act</span>}
    </form>
  );
}

/** Live campaign count for the sidebar card, with a pulsing dot while anything is running. */
function Workspace({ campaigns, needsName }: { campaigns: CampaignView[] | null; needsName: boolean }) {
  const running = campaigns?.filter(c => c.state === "RUNNING") ?? [];
  const locked = campaigns?.filter(c => c.state === "LOCKED_OUT") ?? [];
  const target = locked[0] ?? running[0] ?? null;
  const text = campaigns === null ? "Status unknown" : locked.length ? `${locked.length} locked out` : running.length ? `${running.length} running` : "No campaign running";
  const sub = campaigns === null ? (needsName ? "enter your name to load" : "control plane not reached") : `${campaigns.length} campaign${campaigns.length === 1 ? "" : "s"} in total`;
  const body = <><span className={`pulse${campaigns === null || locked.length ? " bad" : running.length ? "" : " idle"}`} aria-hidden="true" /><span>{text}<small>{sub}</small></span></>;
  return target ? <Link className="side-current" href={`/campaigns/${target.id}`}>{body}</Link> : <div className="side-current">{body}</div>;
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname() ?? "/";
  const active = section(path);
  const reach = useReachability();
  const now = useNow(1000);
  const list = useLoad<{ campaigns: CampaignView[] }>("/v1/campaigns", 5000);
  const campaigns = list.data?.campaigns ?? null;
  const locked = campaigns?.filter(c => c.state === "LOCKED_OUT") ?? [];
  const banner = connectionBanner(reach.unreachable ? "unreachable" : "live", null, reach.lastOkAt, now);
  return (
    <MotionConfig reducedMotion="user"><TooltipProvider><div className="shell">
      <a className="skip" href="#main">Skip to content</a>
      <aside className="sidebar">
        <Link className="brand" href="/" aria-label="ChipCheck console home">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" width="26" height="26" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"><path d="M10 7v4H7m18 0h-3V7M7 21h3v4m12 0v-4h3M11 11h10v10H11z" /><circle cx="16" cy="16" r="2.2" fill="var(--lime)" stroke="none" /></svg>
          </span>
          <div><strong>ChipCheck</strong><small>Research console</small></div>
        </Link>
        <div className="side-caption">Workspace</div>
        <Workspace campaigns={campaigns} needsName={list.error?.code === "UNAUTHENTICATED"} />
        <div className="side-caption flow-caption">Navigate</div>
        <nav aria-label="Main"><ul className="step-nav">{NAV.map((n, i) => (
          <li key={n.href}><Link href={n.href} className={active === n.href ? "active" : undefined} aria-current={active === n.href ? "page" : undefined}>
            {active === n.href ? <motion.i className="nav-pill" layoutId="nav-pill" transition={{ type: "spring", stiffness: 520, damping: 40 }} aria-hidden="true" /> : null}
            <span>{String(i + 1).padStart(2, "0")}</span><b>{n.label}</b>
          </Link></li>
        ))}</ul></nav>
        <div className="side-foot">Planner proposes, safety approves.<br /><span>The E-stop is always the fastest way to stop the bench.</span></div>
      </aside>
      <div className="content">
        <header className="topbar">
          <Crumbs path={path} />
          <div className="topbar-right">
            <NameField />
            <span className={`status${reach.unreachable ? " bad" : ""}`} role="status"><i aria-hidden="true" />{reach.unreachable ? "Control plane unreachable" : "Control plane live"}</span>
          </div>
        </header>
        {banner ? <div className="banner banner-bad" role="alert">{banner}</div> : null}
        {locked.map(c => (
          <div key={c.id} className="banner banner-bad" role="alert">
            Fixture locked out: campaign <Link href={`/campaigns/${c.id}`}>{c.id.slice(0, 12)}</Link> needs a physical inspection and a reviewer reset.{" "}
            <Link href={`/campaigns/${c.id}#lockout`}>Open the lockout page</Link>
          </div>
        ))}
        {/* Keyed by route: the page fades in once on navigation, never on data refreshes. */}
        <motion.main key={path} id="main" className="main-inner" tabIndex={-1}
          initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.24, ease: [0.16, 1, 0.3, 1] }}>
          {children}
        </motion.main>
        <footer className="content-foot"><div><span>ChipCheck / ActiveQual research console</span><span>Requested ≠ measured</span></div></footer>
      </div>
    </div></TooltipProvider></MotionConfig>
  );
}
