"use client"

/**
 * Tactical fingerprint card for a match.
 *
 * The pitch overlay gives a quick visual read on territorial control while
 * the stat grid and fingerprint block explain which historical profile the
 * backend considers the closest tactical match.
 */

import type { MatchState } from "@/types/match"
import { useTactical } from "@/hooks/useTactical"

export function TacticalCard({ state, fixtureId }: { state: MatchState; fixtureId: string }) {
    const { tactical } = useTactical(fixtureId)
    const h = state.home_stats; const a = state.away_stats
    const hasPoss = h.possession > 0 || a.possession > 0
    const totalViz = (h.possession + a.possession) || 100
    const homeZonePct = (h.possession / totalViz) * 100
    const homeDominant = homeZonePct >= 50
    const homeAbbr = state.home_name.slice(0, 3).toUpperCase()
    const awayAbbr = state.away_name.slice(0, 3).toUpperCase()
    const MIN_MATCH_PCT = 45
    const fp = tactical?.home ?? null
    const ppdaDisplay = fp ? fp.match.ppda.toFixed(1)
        : h.shots_total > 0 ? (a.passes_total / h.shots_total).toFixed(1) : "—"
    const hasFingerprint = !!fp && fp.match.match_pct != null && fp.match.match_pct >= MIN_MATCH_PCT

    return (
        <div style={{ display: "flex", flexDirection: "column" }}>

            <div className="tactical-pitch-v2">
                <div className="tactical-pitch-circle" />
                <div className="tactical-pitch-box-home" />
                <div className="tactical-pitch-box-away" />

                <div
                    className="tactical-zone-overlay home"
                    style={{
                        width: hasPoss ? `${homeZonePct.toFixed(1)}%` : "50%",
                        background: homeDominant
                            ? "rgba(79,134,247,.28)"
                            : "rgba(79,134,247,.12)",
                    }}
                >
                    <span className="tactical-zone-label">{homeAbbr}</span>
                </div>

                <div
                    className="tactical-zone-overlay away"
                    style={{
                        width: hasPoss ? `${(100 - homeZonePct).toFixed(1)}%` : "50%",
                        background: !homeDominant
                            ? "rgba(240,84,84,.28)"
                            : "rgba(240,84,84,.12)",
                    }}
                >
                    <span className="tactical-zone-label">{awayAbbr}</span>
                </div>
            </div>

            <div className="tactical-stats-grid tactical-stats-grid-compact">

                <div className="tactical-stat-cell">
                    <span className="tactical-stat-cell-label">Possession</span>
                    <span className="tactical-stat-cell-value" style={{ color: "var(--home)" }}>
                        {hasPoss ? `${h.possession.toFixed(0)}%` : "—"}
                    </span>
                </div>

                <div className="tactical-stat-cell">
                    <span className="tactical-stat-cell-label">Away Poss.</span>
                    <span className="tactical-stat-cell-value" style={{ color: "var(--away)" }}>
                        {hasPoss ? `${a.possession.toFixed(0)}%` : "—"}
                    </span>
                </div>

                <div className="tactical-stat-cell">
                    <span className="tactical-stat-cell-label">Pass Acc. (H)</span>
                    <span className="tactical-stat-cell-value">
                        {h.pass_accuracy > 0 ? `${h.pass_accuracy.toFixed(0)}%` : "—"}
                    </span>
                </div>

                <div className="tactical-stat-cell">
                    <span className="tactical-stat-cell-label">Pass Acc. (A)</span>
                    <span className="tactical-stat-cell-value">
                        {a.pass_accuracy > 0 ? `${a.pass_accuracy.toFixed(0)}%` : "—"}
                    </span>
                </div>

                <div className="tactical-stat-cell">
                    <span className="tactical-stat-cell-label">PPDA</span>
                    <span className="tactical-stat-cell-value">{ppdaDisplay}</span>
                </div>

                <div className="tactical-stat-cell">
                    <span className="tactical-stat-cell-label">Source</span>
                    <span className="tactical-stat-cell-value" style={{ fontSize: ".72rem", color: "var(--c-ai)" }}>
                        {fp ? "Weaviate" : "Live proxy"}
                    </span>
                </div>

            </div>

            <div className="tactical-fingerprint-block">
                <div>
                    <div className="tactical-fp-label">Closest tactical profile</div>
                    {!fp && (
                        <div style={{ fontSize: ".7rem", color: "var(--text-3)", marginTop: 3 }}>
                            Run tactical indexer to enable cosine matching
                        </div>
                    )}
                </div>
                {hasFingerprint ? (
                    <div className="tactical-fp-match">
                        <div style={{ textAlign: "right" }}>
                            <div className="tactical-fp-team">{homeAbbr} ≈ {fp!.match.team}</div>
                            <div style={{ fontFamily: "var(--font-mono)", fontSize: ".58rem", color: "var(--text-3)" }}>
                                {fp!.match.competition} {fp!.match.season}
                            </div>
                        </div>
                        <div className="tactical-fp-pct">{fp!.match.match_pct}%</div>
                    </div>
                ) : (
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: ".68rem", color: "var(--text-3)" }}>
                        {homeDominant ? "High press" : "Low block"}
                        <span style={{ marginLeft: 6, color: "var(--text-3)", fontSize: ".6rem" }}>proxy</span>
                    </div>
                )}
            </div>

            <style jsx>{`
                .tactical-stats-grid-compact {
                    padding: 8px 10px !important;
                    gap: 4px 10px !important;
                }
                .tactical-stats-grid-compact :global(.tactical-stat-cell) {
                    padding: 4px 0 !important;
                }
                .tactical-stats-grid-compact :global(.tactical-stat-cell-label) {
                    font-size: .58rem !important;
                    margin-bottom: 1px !important;
                }
                .tactical-stats-grid-compact :global(.tactical-stat-cell-value) {
                    font-size: .82rem !important;
                }
            `}</style>

        </div>
    )
}