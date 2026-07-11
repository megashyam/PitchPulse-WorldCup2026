"use client"

/**
 * Compact event feed for the match page.
 *
 * Events are rendered as single-line rows to keep the live match column
 * readable while still exposing the most important on-field actions.
 */

import type { MatchState } from "@/types/match"

const EV_ICONS: Record<string, string> = {
    goal: "⚽", own_goal: "⚽", penalty_goal: "⚽",
    yellow: "🟨", red: "🟥", yellow_red: "🟥",
    substitution: "🔄", var: "📺",
}
const EV_LABELS: Record<string, string> = {
    goal: "Goal", own_goal: "Own Goal", penalty_goal: "Penalty Goal",
    yellow: "Yellow Card", red: "Red Card", yellow_red: "2nd Yellow",
    substitution: "Substitution", var: "VAR Review",
}
const HIDDEN_DETAILS = new Set(["worldcup26.ir", "synthesised", "synthesized", "api-sports", "template", "mock", ""])

interface Props { state: MatchState }

export function EventsFeed({ state }: Props) {
    const events = state.events ?? []

    return (
        <div>
            <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "7px 14px 4px" }}>
                <span style={{ fontFamily: "var(--font-mono)", fontSize: ".58rem", textTransform: "uppercase", letterSpacing: ".08em", color: "var(--text-3)" }}>
                    Events
                </span>
            </div>

            {events.length === 0 ? (
                <div style={{ padding: "6px 14px 10px", fontSize: ".72rem", color: "var(--text-3)", fontStyle: "italic" }}>
                    No events yet
                </div>
            ) : (
                events.map((ev, i) => {
                    const isHome = ev.team_name === state.home_name
                    const icon = EV_ICONS[ev.type] ?? "•"
                    const label = EV_LABELS[ev.type] ?? ev.type
                    const showName = ev.player_name && !HIDDEN_DETAILS.has(ev.player_name.toLowerCase())
                    const text = showName ? ev.player_name! : label

                    return (
                        <div key={i} style={{
                            display: "flex", alignItems: "center", gap: 6,
                            padding: "3px 14px", borderTop: "1px solid var(--border)",
                            fontSize: ".74rem", lineHeight: 1.2,
                            justifyContent: isHome ? "flex-start" : "flex-end",
                        }}>
                            {isHome ? (
                                <>
                                    <span style={{ fontFamily: "var(--font-mono)", fontSize: ".68rem", color: "var(--amber)", fontWeight: 600, width: 26 }}>{ev.elapsed}'</span>
                                    <span style={{ fontSize: ".84rem" }}>{icon}</span>
                                    <span style={{ fontWeight: 600, color: "var(--text-1)" }}>{text}</span>
                                    <span style={{ color: "var(--text-3)", fontSize: ".66rem" }}>{ev.team_name}</span>
                                </>
                            ) : (
                                <>
                                    <span style={{ color: "var(--text-3)", fontSize: ".66rem" }}>{ev.team_name}</span>
                                    <span style={{ fontWeight: 600, color: "var(--text-1)" }}>{text}</span>
                                    <span style={{ fontSize: ".84rem" }}>{icon}</span>
                                    <span style={{ fontFamily: "var(--font-mono)", fontSize: ".68rem", color: "var(--amber)", fontWeight: 600, width: 26, textAlign: "right" }}>{ev.elapsed}'</span>
                                </>
                            )}
                        </div>
                    )
                })
            )}
        </div>
    )
}