"use client"

/**
 * Counterfactual analysis panel for live and completed matches.
 *
 * Completed fixtures reuse the persisted history only, while live fixtures
 * keep a small loading card visible during the brief window between the
 * backend starting a simulation and the result stream arriving. That keeps
 * the UI honest about work in progress instead of leaving the previous card
 * in place with no explanation.
 */

import { useCounterfactualStream } from "@/hooks/useCounterfactualStream"
import { useMatchStream } from "@/hooks/useMatchStream"
import type { CfResult, CfCalculating } from "@/hooks/useCounterfactualStream"

interface Props { fixtureId: string }

const EVENT_LABELS: Record<string, string> = {
    goal: "goal",
    own_goal: "own goal",
    penalty_goal: "penalty",
    red: "red card",
    yellow_red: "second yellow",
}

export function CounterfactualPanel({ fixtureId }: Props) {
    const { state } = useMatchStream(fixtureId)
    const { results, calculating, isWaiting } = useCounterfactualStream(fixtureId, state?.status_short)
    const currentElapsed = state?.elapsed ?? 0
    const isCompleted = ["FT", "AET", "PEN"].includes(state?.status_short ?? "")

    const freshResults = isCompleted
        ? results
        : results.filter(r => r.minute <= currentElapsed + 5)

    const showLoader = !!calculating && !freshResults.some(
        r => r.minute === calculating.minute
            && r.event_type === calculating.event_type
            && r.event_team === calculating.event_team
    )

    const isEmpty = freshResults.length === 0 && !showLoader

    return (
        <div style={{ display: "flex", flexDirection: "column" }}>

            <div style={{ padding: "18px 20px 14px", borderBottom: "1px solid var(--border)" }}>
                <div style={{ fontSize: ".8rem", fontWeight: 600, color: "var(--text-1)", marginBottom: 4 }}>
                    Counterfactual Analysis
                </div>
                <div style={{ fontSize: ".72rem", color: "var(--text-3)", lineHeight: 1.45 }}>
                    {isCompleted
                        ? "Full match history — every goal and red card analysed during this match."
                        : "Monte Carlo simulation shows how match trajectories shift after each key event. 50,000 runs computed in ~8 seconds."}
                </div>
            </div>

            {isEmpty ? (
                <div style={{ padding: "32px 20px", textAlign: "center" }}>
                    <div style={{ fontSize: "1.5rem", marginBottom: 10, opacity: .5 }}>🔀</div>
                    <div style={{ fontSize: ".8rem", color: "var(--text-2)", fontWeight: 600, marginBottom: 6 }}>
                        {isCompleted
                            ? "No counterfactual events in this match"
                            : isWaiting ? "Simulating bracket impact…" : "Waiting for a key event"}
                    </div>
                    <div style={{ fontSize: ".72rem", color: "var(--text-3)", lineHeight: 1.5 }}>
                        {isCompleted
                            ? "This match had no goals or red cards that triggered bracket analysis."
                            : "Appears after the first goal or red card, showing how the tournament bracket shifts."}
                    </div>
                </div>
            ) : (
                <>
                    {showLoader && calculating && <CfLoadingCard calculating={calculating} />}
                    {freshResults.map((r, i) => (
                        <CfEventCard key={`${r.minute}-${r.event_type}-${r.event_team}-${i}`} result={r} />
                    ))}
                </>
            )}

        </div>
    )
}

function CfLoadingCard({ calculating }: { calculating: CfCalculating }) {
    const evLabel = EVENT_LABELS[calculating.event_type] ?? calculating.event_type

    return (
        <div className="cf-event-card cf-event-card-loading">
            <div className="cf-event-header">
                <div className="cf-event-left">
                    <div className="cf-event-label">{calculating.minute}' · {evLabel}</div>
                    <div className="cf-event-name">{calculating.event_team}</div>
                </div>
                <div className="cf-event-shift">
                    <span className="cf-loading-spinner" aria-hidden="true" />
                </div>
            </div>

            <div className="cf-event-body">
                <div
                    className="cf-change-summary"
                    style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-2)" }}
                >
                    <span className="cf-loading-spinner cf-loading-spinner-sm" aria-hidden="true" />
                    Running two 50,000-simulation brackets to isolate this event's impact…
                </div>
            </div>

            <style jsx>{`
                .cf-loading-spinner {
                    display: inline-block;
                    width: 16px;
                    height: 16px;
                    border-radius: 50%;
                    border: 2px solid var(--border);
                    border-top-color: var(--accent, #38bdf8);
                    animation: cf-spin 0.8s linear infinite;
                }
                .cf-loading-spinner-sm {
                    width: 12px;
                    height: 12px;
                    border-width: 2px;
                }
                .cf-event-card-loading {
                    opacity: 0.92;
                }
                @keyframes cf-spin {
                    to { transform: rotate(360deg); }
                }
            `}</style>
        </div>
    )
}

function CfEventCard({ result }: { result: CfResult }) {
    const evLabel = EVENT_LABELS[result.event_type] ?? result.event_type
    const shiftPct = (result.path_shift_pct * 100).toFixed(0)
    const top = result.top_changes[0]
    const simK = (result.n_sims / 1000).toFixed(0)
    const isHigh = result.path_shift_pct >= 0.5

    let summary = `${shiftPct}% of ${simK}k simulation paths shifted.`
    if (top) {
        summary += ` ${top.team} ${top.delta > 0 ? "▲" : "▼"} from ${(top.before * 100).toFixed(0)}% → ${(top.after * 100).toFixed(0)}% WC win probability.`
    }

    return (
        <div className="cf-event-card">
            <div className="cf-event-header">
                <div className="cf-event-left">
                    <div className="cf-event-label">{result.minute}' · {evLabel}</div>
                    <div className="cf-event-name">{result.event_team}</div>
                </div>
                <div className="cf-event-shift">
                    <div
                        className="cf-shift-number"
                        style={{ color: isHigh ? "var(--amber)" : "var(--accent)" }}
                    >
                        +{shiftPct}%
                    </div>
                    <div className="cf-shift-label">path shift</div>
                </div>
            </div>

            <div className="cf-event-body">
                <div className="cf-change-summary">{summary}</div>

                {result.narrative && (
                    <div className="cf-narrative-block">
                        <span className="cf-narrative-meta">Mistral 7B · {result.n_sims.toLocaleString()} runs · {result.elapsed_s}s</span>
                        <p className="cf-narrative-text">"{result.narrative}"</p>
                    </div>
                )}
            </div>
        </div>
    )
}
