"use client"



import { useEffect, useState } from "react"
import { useMatchStream } from "@/hooks/useMatchStream"
import { ScoreHeader } from "@/components/match/ScoreHeader"
import { StatsPanel } from "@/components/match/StatsPanel"
import { EventsFeed } from "@/components/match/EventsFeed"
import { MatchTimeline } from "@/components/match/MatchTimeline"
import { MatchAITabs } from "@/components/match/MatchAITabs"
import { RightColumnTabs } from "@/components/match/RightColumnTabs"
import type { MatchState } from "@/types/match"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const TZ = "America/New_York"

interface Props { params: { id: string } }

export default function MatchPage({ params }: Props) {
  const { id } = params
  const [initial, setInitial] = useState<MatchState | null>(null)
  const [initError, setInitError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API}/matches/${id}`)
      .then(r => { if (!r.ok) throw new Error(`${r.status}`); return r.json() })
      .then(setInitial)
      .catch(e => setInitError(e.message))
  }, [id])

  const { state: live, isWaiting, error: streamError } = useMatchStream(id)
  const state = live ?? initial

  if (initError && !state) return (
    <div className="page-error">
      <p>Could not load match <code>{id}</code></p>
      <p className="error-detail">{initError}</p>
      <a href="/" className="back-link">← All matches</a>
    </div>
  )

  if (!state) return (
    <div className="page-loading">
      <div className="spinner" />
      <p>Loading match…</p>
    </div>
  )

  return (
    <div className="match-page">

      { }
      <div className="match-topbar">
        <a href="/" className="back-link">← Matches</a>
        <span className="round-label">{state.round}</span>
        {streamError && <span className="stream-error">⚠ {streamError}</span>}
        {isWaiting && <span className="stream-waiting">Connecting…</span>}
        <span style={{
          marginLeft: "auto", fontFamily: "var(--font-mono)",
          fontSize: ".58rem", color: "var(--text-3)"
        }}>
          Updated {new Date(state.updated_at).toLocaleTimeString("en-US", { timeZone: TZ })}
        </span>
      </div>

      { }
      <div className="match-grid-3">


        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <div className="match-live-col">
            <ScoreHeader state={state} />
            <StatsPanel home={state.home_stats} away={state.away_stats} />
            <EventsFeed state={state} />
            <MatchTimeline state={state} />
          </div>
        </div>


        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <MatchAITabs state={state} fixtureId={id} />
        </div>


        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <RightColumnTabs state={state} fixtureId={id} />
        </div>

      </div>
    </div>
  )
}
