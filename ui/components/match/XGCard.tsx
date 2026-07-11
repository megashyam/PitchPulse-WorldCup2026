"use client"

/**
 * Expected-goals summary card.
 *
 * The card keeps the xG comparison compact: home, difference, and away are
 * shown as three large cells so the user can read the balance of chances at
 * a glance.
 */

import type { MatchState } from "@/types/match"

export function XGCard({ state }: { state: MatchState }) {
    const homeXG = state.home_stats.expected_goals ?? 0
    const awayXG = state.away_stats.expected_goals ?? 0
    const diff = homeXG - awayXG

    return (
        <div className="xg-card-v2">

            <div className="xg-header">
                <div className="xg-header-title">Expected Goals (xG)</div>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: ".58rem", color: "var(--text-3)" }}>
                    StatsBomb native
                </span>
            </div>

            <div className="xg-grid">
                <div className="xg-cell">
                    <div className="xg-cell-value" style={{ color: "var(--home)" }}>
                        {homeXG > 0 ? homeXG.toFixed(2) : "—"}
                    </div>
                    <div className="xg-cell-label">{state.home_name.slice(0, 10)} xG</div>
                </div>

                <div className="xg-cell">
                    <div
                        className="xg-cell-value"
                        style={{
                            color: Math.abs(diff) < 0.1 ? "var(--text-3)"
                                : diff > 0 ? "var(--accent)"
                                    : "var(--away)"
                        }}
                    >
                        {homeXG > 0 || awayXG > 0
                            ? `${diff >= 0 ? "+" : ""}${diff.toFixed(2)}`
                            : "—"}
                    </div>
                    <div className="xg-cell-label">Difference</div>
                </div>

                <div className="xg-cell">
                    <div className="xg-cell-value" style={{ color: "var(--away)" }}>
                        {awayXG > 0 ? awayXG.toFixed(2) : "—"}
                    </div>
                    <div className="xg-cell-label">{state.away_name.slice(0, 10)} xG</div>
                </div>

            </div>

        </div>
    )
}