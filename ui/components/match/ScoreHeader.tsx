"use client"

/**
 * Scoreboard hero for the match page.
 *
 * The header condenses team names, score, status, and elapsed time into a
 * single focal element so the rest of the page can specialize in detailed
 * analysis without repeating the most important match state.
 */

import type { MatchState } from "@/types/match"

const STATUS_LABEL: Record<string, string> = {
    NS: "NOT STARTED", "1H": "1ST HALF", HT: "HALF TIME",
    "2H": "2ND HALF", ET: "EXTRA TIME", BT: "BREAK",
    P: "PENALTIES", FT: "FULL TIME", AET: "AET", PEN: "PENALTIES",
}
const LIVE = new Set(["1H", "2H", "ET", "P"])

export function ScoreHeader({ state }: { state: any }) {
    const isLive = LIVE.has(state.status_short)
    const label = STATUS_LABEL[state.status_short] ?? state.status_short
    const elapsed = state.elapsed ?? 0
    const maxMin = ["2H", "FT", "AET"].includes(state.status_short) ? 90 : 45
    const progress = state.status_short === "FT" ? 100
        : isLive ? Math.min(100, (elapsed / maxMin) * 100) : 0

    return (
        <div className="score-header-v3">
            <div className="score-header-v3-inner">

                <div className="score-team-v3 home">
                    <span className="score-team-name-v3">{state.home_name}</span>
                    {state.venue && <span className="score-team-sub">{state.venue}</span>}
                </div>

                <div className="score-center-v3">
                    <div className="score-digits-v3">
                        <span className="score-digit-v3">{state.home_score}</span>
                        <span className="score-dash-v3">–</span>
                        <span className="score-digit-v3">{state.away_score}</span>
                    </div>
                    <div className="score-status-v3">
                        {isLive && <span className="live-dot" />}
                        <span className="score-status-badge">{label}</span>
                        {isLive && elapsed > 0 && (
                            <span className="score-elapsed-v3">{elapsed}'</span>
                        )}
                    </div>
                </div>

                <div className="score-team-v3 away">
                    <span className="score-team-name-v3">{state.away_name}</span>
                    {state.round && <span className="score-team-sub">{state.round}</span>}
                </div>

            </div>

            <div className="score-header-v3-timeline">
                <div className="score-header-v3-timeline-fill" style={{ width: `${progress.toFixed(1)}%` }} />
            </div>
        </div>
    )
}