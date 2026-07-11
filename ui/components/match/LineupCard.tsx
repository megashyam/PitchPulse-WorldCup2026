"use client"

/**
 * Lineup pitch visualization.
 *
 * The component renders a horizontal pitch with the home team on the left
 * and the away team on the right. Live lineups can include player photos,
 * but the visual always degrades to number-only markers when photo data is
 * missing or fails to load so the pitch remains readable.
 */

import { useEffect, useState } from "react"
import { Flag } from "@/components/Flag"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

interface Player { number: number; name: string; position: string; grid?: string; photo?: string | null }
interface TeamLineup { team: string; formation: string; startingXI: Player[]; coach?: string }
interface LineupData { home: TeamLineup; away: TeamLineup; source: "zafronix" | "api-sports" | "statsbomb_proxy" | "estimated" }

const H_POS: Record<string, [number, number][]> = {
    "4-3-3": [
        [5, 50],
        [30, 10], [30, 33], [30, 67], [30, 90],
        [58, 18], [58, 50], [58, 82],
        [82, 10], [82, 50], [82, 90],
    ],
    "4-4-2": [
        [5, 50],
        [28, 10], [28, 33], [28, 67], [28, 90],
        [58, 10], [58, 35], [58, 65], [58, 90],
        [80, 33], [80, 67],
    ],
    "4-2-3-1": [
        [5, 50],
        [28, 10], [28, 33], [28, 67], [28, 90],
        [50, 30], [50, 70],
        [68, 15], [68, 50], [68, 85],
        [84, 50],
    ],
    "3-5-2": [
        [5, 50],
        [28, 20], [28, 50], [28, 80],
        [52, 5], [58, 28], [58, 50], [58, 72], [52, 95],
        [80, 30], [80, 70],
    ],
    "5-3-2": [
        [5, 50],
        [26, 5], [26, 27], [26, 50], [26, 73], [26, 95],
        [58, 20], [58, 50], [58, 80],
        [80, 30], [80, 70],
    ],
    "4-1-4-1": [
        [5, 50],
        [28, 10], [28, 33], [28, 67], [28, 90],
        [44, 50],
        [65, 10], [65, 35], [65, 65], [65, 90],
        [84, 50],
    ],
    "3-4-3": [
        [5, 50],
        [28, 20], [28, 50], [28, 80],
        [56, 10], [56, 37], [56, 63], [56, 90],
        [82, 10], [82, 50], [82, 90],
    ],
    "3-4-2-1": [
        [5, 50],
        [28, 20], [28, 50], [28, 80],
        [54, 10], [54, 37], [54, 63], [54, 90],
        [72, 30], [72, 70],
        [84, 50],
    ],
}

const ROLES: Record<string, string[]> = {
    "4-3-3": ["GK", "LB", "CB", "CB", "RB", "LCM", "CM", "RCM", "LW", "ST", "RW"],
    "4-4-2": ["GK", "LB", "CB", "CB", "RB", "LM", "LCM", "RCM", "RM", "ST", "ST"],
    "4-2-3-1": ["GK", "LB", "CB", "CB", "RB", "CDM", "CDM", "LM", "CAM", "RM", "ST"],
    "3-5-2": ["GK", "CB", "CB", "CB", "LWB", "CM", "CM", "CM", "RWB", "ST", "ST"],
    "5-3-2": ["GK", "LWB", "CB", "CB", "CB", "RWB", "LCM", "CM", "RCM", "ST", "ST"],
    "4-1-4-1": ["GK", "LB", "CB", "CB", "RB", "CDM", "LM", "LCM", "RCM", "RM", "ST"],
    "3-4-3": ["GK", "CB", "CB", "CB", "LM", "LCM", "RCM", "RM", "LW", "ST", "RW"],
    "3-4-2-1": ["GK", "CB", "CB", "CB", "LM", "LCM", "RCM", "RM", "SS", "SS", "ST"],
}

function shortName(n: string): string {
    if (!n) return ""
    const p = n.trim().split(" ")
    return p.length === 1 ? n : p[p.length - 1]
}

const VW = 200, VH = 100
const R = 5.5   // dot radius
const NFS = 3.0  // number font size
const LFS = 2.8  // label font size

interface PlayerDotProps {
    x: number; y: number
    num: string; trimmed: string
    player?: Player
    fill: string; stroke: string; numColor: string
    idKey: string
}

function PlayerDot({ x, y, num, trimmed, player, fill, stroke, numColor, idKey }: PlayerDotProps) {
    const [imgFailed, setImgFailed] = useState(false)
    const hasPhoto = !!player?.photo && !imgFailed
    const clipId = `pd-clip-${idKey}`

    return (
        <g>
            <circle cx={x} cy={y} r={R + 1} fill="rgba(0,0,0,0.25)" />
            <circle cx={x} cy={y} r={R} fill={fill} stroke={stroke} strokeWidth={1} />

            {hasPhoto && (
                <>
                    <clipPath id={clipId}>
                        <circle cx={x} cy={y} r={R - 0.4} />
                    </clipPath>
                    <g transform={`rotate(-90 ${x} ${y})`}>
                        <image
                            href={player!.photo!}
                            x={x - R} y={y - R}
                            width={R * 2} height={R * 2}
                            clipPath={`url(#${clipId})`}
                            preserveAspectRatio="xMidYMid slice"
                            onError={() => setImgFailed(true)}
                        />
                    </g>
                </>
            )}

            {hasPhoto ? (
                <>
                    <circle cx={x + R - 1.4} cy={y + R - 1.4} r={2.1} fill={fill} stroke={stroke} strokeWidth={0.5} />
                    <g transform={`rotate(-90 ${x + R - 1.4} ${y + R - 1.3})`}>
                        <text x={x + R - 1.4} y={y + R - 1.3}
                            textAnchor="middle" dominantBaseline="middle"
                            fontSize={1.9} fontWeight="bold" fill={numColor} fontFamily="monospace">
                            {num}
                        </text>
                    </g>
                </>
            ) : (
                <g transform={`rotate(-90 ${x} ${y + 0.5})`}>
                    <text x={x} y={y + 0.5}
                        textAnchor="middle" dominantBaseline="middle"
                        fontSize={NFS} fontWeight="bold" fill={numColor} fontFamily="monospace">
                        {num}
                    </text>
                </g>
            )}

            {trimmed && (
                <g transform={`rotate(-90 ${x} ${y + R + 3.5})`}>
                    <text x={x} y={y + R + 3.5}
                        textAnchor="middle" dominantBaseline="hanging"
                        fontSize={LFS} fill="rgba(255,255,255,0.9)"
                        fontFamily="Arial, sans-serif">
                        {trimmed}
                    </text>
                </g>
            )}
        </g>
    )
}

interface DotsProps {
    lineup: TeamLineup
    isHome: boolean
    fill: string
    stroke: string
    numColor: string
    lbl: string
}

function Dots({ lineup, isHome, fill, stroke, numColor, lbl }: DotsProps) {
    const pos = H_POS[lineup.formation] ?? H_POS["4-3-3"]
    const roles = ROLES[lineup.formation] ?? ROLES["4-3-3"]

    return (
        <>
            {pos.map((p, i) => {
                const baseX = (p[0] / 100) * (VW / 2)
                const baseY = (p[1] / 100) * VH
                const x = isHome ? baseX : (VW - baseX)
                const y = baseY
                const player = lineup.startingXI[i]
                const num = player ? String(player.number) : String(i + 1)
                const name_ = player ? shortName(player.name) : (roles[i] ?? "")
                const trimmed = name_.length > 9 ? name_.slice(0, 8) + "." : name_

                return (
                    <PlayerDot
                        key={i}
                        x={x} y={y}
                        num={num} trimmed={trimmed}
                        player={player}
                        fill={fill} stroke={stroke} numColor={numColor}
                        idKey={`${lbl}-${i}`}
                    />
                )
            })}
        </>
    )
}

interface Props { fixtureId: string; homeTeam: string; awayTeam: string }

export function LineupCard({ fixtureId, homeTeam, awayTeam }: Props) {
    const [data, setData] = useState<LineupData | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!fixtureId) return
        const load = () =>
            fetch(`${API}/matches/${fixtureId}/lineups`)
                .then(r => r.ok ? r.json() : null)
                .then(d => { if (d) setData(d) })
                .catch(() => { })
                .finally(() => setLoading(false))
        load()
        const t = setInterval(load, 60_000)
        return () => clearInterval(t)
    }, [fixtureId])

    const home: TeamLineup = data?.home ?? { team: homeTeam, formation: "4-3-3", startingXI: [] }
    const away: TeamLineup = data?.away ?? { team: awayTeam, formation: "4-4-2", startingXI: [] }
    const isLive = data?.source === "api-sports"
    const isReal = data?.source === "api-sports" || data?.source === "zafronix"
    const isZafronix = data?.source === "zafronix"
    const isProxy = data?.source === "statsbomb_proxy"
    const homeAbbr = homeTeam.slice(0, 3).toUpperCase()
    const awayAbbr = awayTeam.slice(0, 3).toUpperCase()
    const photoCount = [...home.startingXI, ...away.startingXI].filter(p => p.photo).length

    return (
        <div>
            <div style={{
                display: "grid", gridTemplateColumns: "1fr auto 1fr",
                alignItems: "center", padding: "10px 14px 8px",
                borderBottom: "1px solid var(--border)", gap: 6,
                background: "var(--bg-3)",
            }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <Flag team={homeTeam} size="sm" />
                    <span style={{
                        fontFamily: "var(--font-mono)", fontSize: ".72rem",
                        fontWeight: 700, color: "var(--home)"
                    }}>
                        {homeAbbr}
                    </span>
                    <span style={{
                        fontFamily: "var(--font-mono)", fontSize: ".68rem",
                        color: "var(--text-2)", background: "var(--bg-2)",
                        padding: "2px 8px", borderRadius: 4, border: "1px solid var(--border)"
                    }}>
                        {home.formation}
                    </span>
                </div>

                <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 3 }}>
                    <span style={{
                        fontFamily: "var(--font-mono)", fontSize: ".6rem",
                        textTransform: "uppercase", letterSpacing: ".12em",
                        color: "var(--text-3)"
                    }}>
                        Formation
                    </span>
                    {isLive && (
                        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                            <span className="live-dot" style={{ width: 5, height: 5 }} />
                            <span style={{
                                fontFamily: "var(--font-mono)", fontSize: ".54rem",
                                color: "var(--amber)", textTransform: "uppercase"
                            }}>live</span>
                        </div>
                    )}
                    {isZafronix && (
                        <span style={{
                            fontFamily: "var(--font-mono)", fontSize: ".54rem",
                            color: "var(--c-data)", textTransform: "uppercase"
                        }}>2026 squad</span>
                    )}
                    {isProxy && (
                        <span style={{
                            fontFamily: "var(--font-mono)", fontSize: ".54rem",
                            color: "var(--c-ai)", textTransform: "uppercase"
                        }}>historical proxy</span>
                    )}
                    {loading && (
                        <span style={{
                            fontFamily: "var(--font-mono)", fontSize: ".54rem",
                            color: "var(--text-3)"
                        }}>loading…</span>
                    )}
                </div>

                <div style={{ display: "flex", alignItems: "center", gap: 7, justifyContent: "flex-end" }}>
                    <span style={{
                        fontFamily: "var(--font-mono)", fontSize: ".68rem",
                        color: "var(--text-2)", background: "var(--bg-2)",
                        padding: "2px 8px", borderRadius: 4, border: "1px solid var(--border)"
                    }}>
                        {away.formation}
                    </span>
                    <span style={{
                        fontFamily: "var(--font-mono)", fontSize: ".72rem",
                        fontWeight: 700, color: "var(--away)"
                    }}>
                        {awayAbbr}
                    </span>
                    <Flag team={awayTeam} size="sm" />
                </div>
            </div>

            <div style={{
                background: "#1a5c30",
                position: "relative",
                overflow: "hidden",
                aspectRatio: `${VH} / ${VW}`,
                width: "100%",
                maxWidth: 420,
                margin: "0 auto",
            }}>
                <div style={{
                    position: "absolute",
                    top: "50%", left: "50%",
                    width: `${(VW / VH) * 100}%`,
                    transform: "translate(-50%, -50%) rotate(90deg)",
                    transformOrigin: "center center",
                }}>
                    <svg
                        viewBox={`0 0 ${VW} ${VH}`}
                        style={{ display: "block", width: "100%", height: "auto" }}
                        xmlns="http://www.w3.org/2000/svg"
                    >
                        <rect x="1" y="1" width={VW - 2} height={VH - 2}
                            fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="0.6" />
                        <line x1={VW / 2} y1="1" x2={VW / 2} y2={VH - 1}
                            stroke="rgba(255,255,255,0.2)" strokeWidth="0.7" />
                        <circle cx={VW / 2} cy={VH / 2} r="11"
                            fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="0.6" />
                        <circle cx={VW / 2} cy={VH / 2} r="0.8" fill="rgba(255,255,255,0.3)" />
                        <rect x="1" y="28" width="18" height="44"
                            fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="0.5" />
                        <rect x="1" y="36" width="7" height="28"
                            fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth="0.4" />
                        <rect x={VW - 19} y="28" width="18" height="44"
                            fill="none" stroke="rgba(255,255,255,0.12)" strokeWidth="0.5" />
                        <rect x={VW - 8} y="36" width="7" height="28"
                            fill="none" stroke="rgba(255,255,255,0.09)" strokeWidth="0.4" />
                        {[0, 1, 2, 3].map(i => (
                            <rect key={i} x={i * 50} y="0" width="50" height={VH}
                                fill={i % 2 === 0 ? "rgba(0,0,0,0.06)" : "transparent"} />
                        ))}

                        <Dots lineup={home} isHome={true}
                            fill="#ffffff" stroke="rgba(0,0,0,0.25)"
                            numColor="#111" lbl={homeAbbr} />
                        <Dots lineup={away} isHome={false}
                            fill="#1a1a2e" stroke="rgba(255,255,255,0.4)"
                            numColor="#fff" lbl={awayAbbr} />
                    </svg>
                </div>
            </div>

            <div style={{
                padding: "6px 14px", borderTop: "1px solid var(--border)",
                fontFamily: "var(--font-mono)", fontSize: ".58rem",
                color: "var(--text-3)", textAlign: "center",
                background: "var(--bg-3)"
            }}>
                {isLive
                    ? `Live lineups via API-Sports · ${home.startingXI.length + away.startingXI.length} players${photoCount ? ` · ${photoCount} photos` : ""}`
                    : isZafronix
                        ? `2026 tournament squads via Zafronix WC API · ${home.startingXI.length + away.startingXI.length} players${photoCount ? ` · ${photoCount} photos` : ""}`
                        : isProxy
                            ? `Historical proxy lineup (StatsBomb) — not this match's confirmed XI · ${home.startingXI.length + away.startingXI.length} players${photoCount ? ` · ${photoCount} photos` : ""}`
                            : "Lineups not confirmed · formation estimated"}
            </div>

            {(home.coach || away.coach) && (
                <div style={{
                    display: "grid", gridTemplateColumns: "1fr auto 1fr",
                    padding: "8px 14px", borderTop: "1px solid var(--border)",
                    alignItems: "center", gap: 8
                }}>
                    <span style={{ fontSize: ".72rem", color: "var(--text-2)" }}>{home.coach ?? "—"}</span>
                    <span style={{
                        fontFamily: "var(--font-mono)", fontSize: ".56rem",
                        textTransform: "uppercase", letterSpacing: ".08em", color: "var(--text-3)"
                    }}>
                        Coach
                    </span>
                    <span style={{ fontSize: ".72rem", color: "var(--text-2)", textAlign: "right" }}>{away.coach ?? "—"}</span>
                </div>
            )}
        </div>
    )
}