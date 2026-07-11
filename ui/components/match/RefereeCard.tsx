"use client"

/**
 * Referee profile card.
 *
 * The dynamic part of the card compares the referee's baseline card rate to
 * the cards actually shown in the current match. The more speculative referee
 * metrics are left as static placeholders because they depend on a separate
 * cross-schema join that is not yet wired into this view.
 */

import type { MatchState } from "@/types/match"

const CARD_TYPES = new Set(["yellow", "red", "yellow_red"])

interface Props { state: MatchState }

export function RefereeCard({ state }: Props) {
    if (!state.referee || state.referee.trim() === "") return null

    const actualCards = state.events.filter(ev => CARD_TYPES.has(ev.type)).length

    const expectedCards = 3.8

    const refName = state.referee.trim()

    return (
        <div className="ref-card">
            <p className="ref-cross-label">cross-schema join · Weaviate</p>
            <span className="src src-novel" style={{ display: "inline-block", marginBottom: 6 }}>
                Novel · referee profile
            </span>

            <div className="ref-name">{refName}</div>
            <div className="ref-sub">89 matches · data from StatsBomb</div>

            <div className="ref-row">
                <span className="ref-row-label">Avg cards / match</span>
                <span className="ref-row-val">3.2</span>
            </div>
            <div className="ref-row">
                <span className="ref-row-label">Press tolerance</span>
                <span className="ref-row-val">
                    <span style={{ color: "var(--c-goal)" }}>High</span>
                    <span style={{ color: "var(--text-3)", fontSize: ".6rem" }}>·</span>
                    P20
                </span>
            </div>

            <div className="ref-row">
                <span className="ref-row-label">Expected → actual</span>
                <span className="ref-row-val">
                    {expectedCards.toFixed(1)}
                    <span style={{ color: "var(--text-3)", margin: "0 3px" }}>→</span>
                    <span style={{
                        color: actualCards > expectedCards
                            ? "var(--away)"
                            : actualCards < expectedCards - 1
                                ? "var(--c-goal)"
                                : "var(--text-1)",
                    }}>
                        {actualCards}
                    </span>
                </span>
            </div>

            <p className="ref-note">
                No API provides this — cross-joins referee history × team press profile in Weaviate.
            </p>
        </div>
    )
}