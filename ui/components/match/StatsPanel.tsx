"use client"

/**
 * Compact bilateral team stats panel.
 *
 * The layout keeps home and away numbers aligned around a shared label so the
 * viewer can compare the two sides at a glance. Possession gets a dedicated
 * bar because raw percentages are easier to read as a visual balance.
 */

import type { TeamStats } from "@/types/match"

interface Props { home: TeamStats; away: TeamStats }

function StatRow({ label, home, away, format, showBar }: {
    label: string; home: number; away: number;
    format?: (v: number) => string; showBar?: boolean
}) {
    const h = home ?? 0
    const a = away ?? 0
    const fmt = format ?? ((v: number) => String(v))
    const total = h + a || 100
    const hp = (h / total) * 100
    const ap = (a / total) * 100

    return (
        <div className={`stat-row-v2${showBar ? " possession-row" : ""}`}>
            <span className="stat-num-home">{fmt(h)}</span>
            <div className="stat-center-col">
                <span className="stat-center-name">{label}</span>
                {showBar && (
                    <div className="stat-poss-bar">
                        <div className="stat-poss-home" style={{ width: `${hp.toFixed(1)}%` }} />
                        <div className="stat-poss-away" style={{ width: `${ap.toFixed(1)}%` }} />
                    </div>
                )}
            </div>
            <span className="stat-num-away">{fmt(a)}</span>
        </div>
    )
}

export function StatsPanel({ home, away }: Props) {
    return (
        <div className="stats-panel-v2">

            <div className="stats-section-header">Attack</div>

            <StatRow
                label="Possession"
                home={home.possession} away={away.possession}
                format={v => `${v}%`} showBar
            />
            <StatRow label="Shots" home={home.shots_total} away={away.shots_total} />
            <StatRow label="On Target" home={home.shots_on_goal} away={away.shots_on_goal} />
            <StatRow
                label="xG"
                home={home.expected_goals} away={away.expected_goals}
                format={v => (v ?? 0).toFixed(2)}
            />

            <div className="stats-section-header" style={{ marginTop: 0 }}>Passing</div>

            <StatRow
                label="Pass Acc."
                home={home.pass_accuracy} away={away.pass_accuracy}
                format={v => `${v}%`}
            />
            <StatRow label="Passes" home={home.passes_total} away={away.passes_total} />
            <StatRow label="Corners" home={home.corner_kicks} away={away.corner_kicks} />

        </div>
    )
}