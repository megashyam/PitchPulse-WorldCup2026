"use client"

/**
 * Live win probability card for the match view.
 *
 * The backend supplies the primary in-play probability model so the UI stays
 * aligned with the same simulation stack used by counterfactual analysis.
 * A local heuristic remains only as a fallback when the live endpoint is
 * unavailable, which keeps the card informative instead of blank.
 */

import { useEffect, useState } from "react"
import { useMomentumStream } from "@/hooks/useMomentumStream"
import type { MatchState } from "@/types/match"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const POLL_INTERVAL = 30_000

interface Props { state: MatchState; fixtureId: string }

interface LiveProbResponse {
    fixture_id: number
    elapsed: number
    status_short: string
    home_win: number
    draw: number
    away_win: number
    pre_match_source: string
}

function calcProbs(
    homeGoals: number, awayGoals: number,
    homeMom: number, elapsed: number, status: string
): { home: number; draw: number; away: number } {
    const FT = ["FT", "AET", "PEN"].includes(status)
    if (FT) {
        if (homeGoals > awayGoals) return { home: 1, draw: 0, away: 0 }
        if (awayGoals > homeGoals) return { home: 0, draw: 0, away: 1 }
        return { home: 0, draw: 1, away: 0 }
    }

    const NS = status === "NS"
    if (NS) return { home: 0.45, draw: 0.27, away: 0.28 }

    const maxMin = 90
    const timeElapsed = Math.min(1, (elapsed ?? 45) / maxMin)
    const certainty = timeElapsed ** 0.7

    const diff = homeGoals - awayGoals
    const momAdv = (homeMom - 0.5) * 0.3

    let pH = 0.45 + momAdv
    let pD = 0.27
    let pA = 0.28 - momAdv

    if (diff > 0) {
        pH += certainty * (0.35 * Math.min(diff, 2))
        pD -= certainty * 0.12
        pA -= certainty * (0.23 * Math.min(diff, 2))
    } else if (diff < 0) {
        pA += certainty * (0.35 * Math.min(-diff, 2))
        pD -= certainty * 0.12
        pH -= certainty * (0.23 * Math.min(-diff, 2))
    }

    const total = pH + pD + pA
    return {
        home: Math.max(0.02, pH / total),
        draw: Math.max(0.02, pD / total),
        away: Math.max(0.02, pA / total),
    }
}

export function LiveProbCard({ state, fixtureId }: Props) {
    const { momentum } = useMomentumStream(fixtureId)
    const [live, setLive] = useState<LiveProbResponse | null>(null)
    const [usingFallback, setUsingFallback] = useState(false)

    useEffect(() => {
        let cancelled = false

        async function load() {
            try {
                const r = await fetch(`${API}/matches/${fixtureId}/live-prob`)
                if (!r.ok) throw new Error(`${r.status}`)
                const data: LiveProbResponse = await r.json()
                if (!cancelled) {
                    setLive(data)
                    setUsingFallback(false)
                }
            } catch {
                if (!cancelled) setUsingFallback(true)
            }
        }

        load()
        const t = setInterval(load, POLL_INTERVAL)
        return () => { cancelled = true; clearInterval(t) }
    }, [fixtureId])

    const homeMom = momentum?.home.momentum_score ?? 0.5
    const elapsed = state.elapsed ?? 0

    const probs = live && !usingFallback
        ? { home: live.home_win, draw: live.draw, away: live.away_win }
        : calcProbs(state.home_score, state.away_score, homeMom, elapsed, state.status_short)

    const isLive = ["1H", "HT", "2H", "ET", "P", "LIVE"].includes(state.status_short)
    const isFT = ["FT", "AET", "PEN"].includes(state.status_short)

    const hn = state.home_name.length > 10
        ? state.home_name.split(" ").pop()!
        : state.home_name
    const an = state.away_name.length > 10
        ? state.away_name.split(" ").pop()!
        : state.away_name

    const homeW = Math.round(probs.home * 100)
    const drawW = Math.round(probs.draw * 100)
    const awayW = 100 - homeW - drawW

    const modelNote = usingFallback || !live
        ? `Score + momentum heuristic${momentum ? " · EWMA" : ""} (offline fallback)`
        : `In-play model · ${live.pre_match_source} prior`

    return (
        <div style={{
            background: "var(--bg-2)",
            border: "1px solid var(--border)",
            borderTop: "2px solid var(--c-data)",
            borderRadius: "var(--r-lg)",
            overflow: "hidden",
        }}>

            <div style={{
                padding: "11px 14px 8px",
                borderBottom: "1px solid var(--border)",
                display: "flex", alignItems: "center", justifyContent: "space-between",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <div style={{
                        width: 22, height: 22, borderRadius: 7,
                        background: "rgba(56,189,248,0.12)",
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: ".82rem",
                    }}>🎲</div>
                    <span style={{ fontSize: ".78rem", fontWeight: 700, color: "var(--text-1)" }}>
                        Win Probability
                    </span>
                </div>
                <span style={{
                    fontFamily: "var(--font-mono)", fontSize: ".56rem",
                    textTransform: "uppercase", letterSpacing: ".06em",
                    color: isLive ? "var(--c-data)" : "var(--text-3)",
                    padding: "2px 8px", borderRadius: 10,
                    background: isLive ? "rgba(56,189,248,0.1)" : "var(--bg-3)",
                }}>
                    {isFT ? "Final" : isLive ? `${elapsed}' live` : "Pre-match"}
                </span>
            </div>

            <div style={{ padding: "12px 14px 10px" }}>

                <div style={{ display: "grid", gridTemplateColumns: "1fr auto 1fr", gap: 6, marginBottom: 8, alignItems: "center" }}>
                    <div>
                        <div style={{ fontSize: ".7rem", fontWeight: 700, color: "var(--home)" }}>{hn}</div>
                        <div style={{ fontFamily: "var(--font-display)", fontSize: "1.4rem", color: "var(--home)", lineHeight: 1 }}>
                            {homeW}%
                        </div>
                    </div>
                    <div style={{ textAlign: "center" }}>
                        <div style={{ fontSize: ".58rem", fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em" }}>Draw</div>
                        <div style={{ fontFamily: "var(--font-display)", fontSize: "1.1rem", color: "var(--text-2)", lineHeight: 1 }}>
                            {drawW}%
                        </div>
                    </div>
                    <div style={{ textAlign: "right" }}>
                        <div style={{ fontSize: ".7rem", fontWeight: 700, color: "var(--away)" }}>{an}</div>
                        <div style={{ fontFamily: "var(--font-display)", fontSize: "1.4rem", color: "var(--away)", lineHeight: 1 }}>
                            {awayW}%
                        </div>
                    </div>
                </div>

                <div style={{ height: 7, borderRadius: 4, overflow: "hidden", display: "flex", gap: 2 }}>
                    <div style={{ width: `${homeW}%`, background: "var(--home)", borderRadius: "4px 0 0 4px", transition: "width .6s ease" }} />
                    <div style={{ width: `${drawW}%`, background: "var(--text-3)", transition: "width .6s ease" }} />
                    <div style={{ width: `${awayW}%`, background: "var(--away)", borderRadius: "0 4px 4px 0", transition: "width .6s ease" }} />
                </div>

                <div style={{ marginTop: 7, fontFamily: "var(--font-mono)", fontSize: ".56rem", color: "var(--text-3)" }}>
                    {modelNote}
                </div>

            </div>
        </div>
    )
}
