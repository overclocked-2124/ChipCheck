"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { useLoad, useNow, useReachability } from "@/components/api";
import { actorCookie, readActor } from "@/lib/client";
import { connectionBanner } from "@/lib/live";
import type { CampaignView } from "@/lib/types";

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
      <label>Your name
        <input value={name} onChange={e => { setName(e.target.value); setInvalid(false); }} onBlur={() => { if (name.trim() && name.trim() !== saved) save(); }}
          placeholder="recorded with every action" autoComplete="name" aria-invalid={invalid} maxLength={60} />
      </label>
      {invalid ? <span className="bad-text" role="alert">Letters, digits, space . _ - only</span> : saved ? <span className="hint">Recorded as {saved}</span> : <span className="bad-text">Enter your name to act</span>}
    </form>
  );
}

function Banners() {
  const reach = useReachability();
  const now = useNow(1000);
  const campaigns = useLoad<{ campaigns: CampaignView[] }>("/v1/campaigns", 5000);
  const locked = campaigns.data?.campaigns.filter(c => c.state === "LOCKED_OUT") ?? [];
  const banner = connectionBanner(reach.unreachable ? "unreachable" : "live", null, reach.lastOkAt, now);
  return (
    <>
      {banner ? <div className="banner banner-bad" role="alert">{banner}</div> : null}
      {locked.map(c => (
        <div key={c.id} className="banner banner-bad" role="alert">
          Fixture locked out: campaign <Link href={`/campaigns/${c.id}`}>{c.id}</Link> needs a physical inspection and a reviewer reset.{" "}
          <Link href={`/campaigns/${c.id}#lockout`}>Open the lockout page</Link>
        </div>
      ))}
    </>
  );
}

const NAV: [string, string][] = [["/", "Campaigns"], ["/contracts", "Contracts"], ["/fixtures", "Fixtures"], ["/campaigns/new", "New campaign"], ["/compare", "Compare"]];

export function Shell({ children }: { children: ReactNode }) {
  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="topbar">
        <Link href="/" className="brand">ActiveQual</Link>
        <nav aria-label="Main">{NAV.map(([href, label]) => <Link key={href} href={href}>{label}</Link>)}</nav>
        <NameField />
      </header>
      <Banners />
      <main id="main">{children}</main>
    </>
  );
}
