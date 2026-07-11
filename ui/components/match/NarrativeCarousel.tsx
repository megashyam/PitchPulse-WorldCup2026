"use client"

/**
 * Narrative carousel for the match page.
 *
 * The top panel shows the selected spike and its synthesized arc, while the
 * grid below provides a compact ranked view of all trending stories. Local
 * state only tracks presentation concerns such as the selected spike and the
 * active source filter.
 */

import { useState } from "react"
import { useNarrativeStream } from "@/hooks/useNarrativeStream"
import { Flag } from "@/components/Flag"
import { CommentBubbles } from "@/components/narrative/CommentBubbles"

const SRC_ICONS: Record<string, string> = {
    mastodon: "🐘", bluesky: "🦋", trends: "📈", wikipedia: "📖",
}
const SRC_LABELS: Record<string, string> = {
    mastodon: "Mastodon", bluesky: "Bluesky", trends: "Trends", wikipedia: "Wikipedia",
}
const SRC_UNITS: Record<string, string> = {
    mastodon: "posts/min", bluesky: "mentions/min", trends: "index 0-100", wikipedia: "edits/min",
}
const SRC_MAX: Record<string, number> = {
    mastodon: 50, bluesky: 40, trends: 100, wikipedia: 10,
}
const SRC_COLOR: Record<string, string> = {
    mastodon: "#6364FF", bluesky: "#4f86f7", trends: "#f59e0b", wikipedia: "#10d9a0",
}
const NAME_ALIAS: Record<string, string> = {
    "United States": "USA", "United States of America": "USA",
    "Korea Republic": "South Korea", "IR Iran": "Iran",
}
const canonTeam = (n?: string) => (n ? NAME_ALIAS[n] ?? n : "")
const SOURCES = ["mastodon", "bluesky", "trends", "wikipedia"] as const

function isTeamTopic(topic: string) {
    return !["WC2026", "WorldCup2026"].includes(topic)
}

function seededPoints(seed: string, n = 8): number[] {
    let h = 0
    for (let i = 0; i < seed.length; i++) { h = (h << 5) - h + seed.charCodeAt(i); h |= 0 }
    const pts: number[] = []
    let v = 0.3 + (Math.abs(h % 100) / 100) * 0.2
    for (let i = 0; i < n; i++) {
        h = (h * 1103515245 + 12345) & 0x7fffffff
        v = Math.max(0.1, Math.min(0.95, v + ((h % 100) / 100 - 0.42) * 0.25))
        pts.push(v)
    }
    return pts
}

function Sparkline({ seed, color }: { seed: string; color: string }) {
    const pts = seededPoints(seed)
    const w = 100, h = 26
    const step = w / (pts.length - 1)
    const path = pts.map((p, i) => `${i === 0 ? "M" : "L"} ${(i * step).toFixed(1)} ${(h - p * h).toFixed(1)}`).join(" ")
    const areaPath = `${path} L ${w} ${h} L 0 ${h} Z`
    return (
        <svg viewBox={`0 0 ${w} ${h}`} style={{ width: "100%", height: h, display: "block" }}>
            <path d={areaPath} fill={color} opacity={0.12} />
            <path d={path} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
        </svg>
    )
}

function severityColor(sev: number): string {
    if (sev >= 0.7) return "#f05454"
    if (sev >= 0.4) return "#f59e0b"
    return "#10d9a0"
}

export function NarrativeCarousel({ homeTeam, awayTeam }: { homeTeam?: string; awayTeam?: string }) {
    const { spikes, isWarming, isWaiting } = useNarrativeStream()
    const [selectedId, setSelectedId] = useState<string | null>(null)
    const [commentsOpen, setCommentsOpen] = useState(false)
    const [selSource, setSelSource] = useState<string | null>(null)

    const matchTeams = new Set(
        [canonTeam(homeTeam), canonTeam(awayTeam)].filter(Boolean)
    )
    const trending = [...spikes].sort((a, b) => b.severity - a.severity)
    const spikeCount = trending.length

    const selected = trending.find(s => s.spike_id === selectedId) ?? trending[0] ?? null

    const drivingDefault = selected
        ? (selected.source_names?.[0]
            ?? SOURCES.reduce((a, b) =>
                (selected!.sources[b] ?? 0) / SRC_MAX[b] > (selected!.sources[a] ?? 0) / SRC_MAX[a] ? b : a,
                SOURCES[0]))
        : "mastodon"
    const activeSource =
        selSource && selected && (selected.sources as Record<string, number>)[selSource] != null
            ? selSource
            : drivingDefault

    if (isWarming || (isWaiting && spikes.length === 0)) return (
        <div style={{ padding: "24px 16px", textAlign: "center" }}>
            <div style={{ fontSize: "1.4rem", marginBottom: 8, opacity: .5 }}>📡</div>
            <div style={{ fontSize: ".8rem", fontWeight: 600, color: "var(--text-1)", marginBottom: 4 }}>
                {isWarming ? "Building baseline…" : "No spikes yet"}
            </div>
            <div style={{ fontSize: ".72rem", color: "var(--text-3)" }}>
                Live narrative spikes will appear here as they're detected
            </div>
        </div>
    )

    if (trending.length === 0) return (
        <div style={{ padding: "24px 16px", textAlign: "center" }}>
            <div style={{ fontSize: "1.4rem", marginBottom: 8, opacity: .5 }}>🔥</div>
            <div style={{ fontSize: ".8rem", fontWeight: 600, color: "var(--text-1)", marginBottom: 4 }}>
                No trending stories yet
            </div>
            <div style={{ fontSize: ".72rem", color: "var(--text-3)" }}>
                Trending narrative spikes across the tournament will appear here as they're detected
            </div>
        </div>
    )

    return (
        <div>

            {selected && (
                <div style={{ padding: "16px 14px", borderBottom: "1px solid var(--border-bright)" }}>

                    <div style={{ marginBottom: 16 }}>
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: ".58rem", textTransform: "uppercase", letterSpacing: ".1em", color: "var(--c-ai)", display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                            <span style={{ width: 3, height: 10, background: "var(--c-ai)", borderRadius: 2, flexShrink: 0 }} />
                            Mistral 7B · Arc Synthesis · Weaviate RAG
                        </div>
                        <div style={{ background: "var(--bg-3)", border: "1px solid var(--border)", borderRadius: "var(--r-md)", padding: "12px 14px" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                                <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--c-ai)", flexShrink: 0 }} />
                                <span style={{ fontFamily: "var(--font-mono)", fontSize: ".56rem", textTransform: "uppercase", letterSpacing: ".08em", color: "var(--text-3)" }}>
                                    Narrative Arc
                                </span>
                            </div>
                            {selected.arc ? (
                                <p style={{ fontSize: ".78rem", color: "var(--text-1)", fontStyle: "italic", lineHeight: 1.55, margin: 0 }}>
                                    "{selected.arc}"
                                </p>
                            ) : (
                                <p style={{ fontSize: ".76rem", color: "var(--text-2)", lineHeight: 1.5, margin: 0 }}>
                                    {selected.summary}
                                </p>
                            )}
                        </div>
                    </div>

                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 8 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            {isTeamTopic(selected.topic)
                                ? <Flag team={selected.topic} size="md" />
                                : <span style={{ fontSize: "1.6rem" }}>🌍</span>}
                            <span style={{ fontFamily: "var(--font-display)", fontSize: "1.5rem", letterSpacing: ".02em", color: "var(--text-1)" }}>
                                {selected.topic.toUpperCase()}
                            </span>
                            {matchTeams.has(canonTeam(selected.topic)) && (
                                <span style={{ fontFamily: "var(--font-mono)", fontSize: ".52rem", color: "var(--accent)", border: "1px solid var(--accent-glow)", borderRadius: 4, padding: "1px 4px", alignSelf: "center" }}>THIS MATCH</span>
                            )}
                        </div>
                        <div style={{ textAlign: "right" }}>
                            <div style={{ fontFamily: "var(--font-display)", fontSize: "1.6rem", color: severityColor(selected.severity), lineHeight: 1 }}>
                                {Math.round(selected.severity * 100)}%
                            </div>
                            <div style={{ fontFamily: "var(--font-mono)", fontSize: ".56rem", color: "var(--text-3)", textTransform: "uppercase" }}>
                                above baseline
                            </div>
                        </div>
                    </div>

                    <p style={{ fontSize: ".76rem", color: "var(--text-2)", marginBottom: 10 }}>{selected.summary}</p>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6, marginBottom: 10 }}>
                        {SOURCES.map(src => {
                            const val = selected.sources[src] ?? 0
                            const driving = selected.source_names?.includes(src)
                            const active = activeSource === src
                            const color = SRC_COLOR[src]
                            return (
                                <button key={src} onClick={() => setSelSource(src)} style={{
                                    background: active ? `${color}22` : driving ? `${color}12` : "var(--bg-3)",
                                    border: `1px solid ${active ? color : driving ? color + "40" : "var(--border)"}`,
                                    borderRadius: 6, padding: "5px 6px", textAlign: "center", position: "relative", cursor: "pointer",
                                }}>
                                    {driving && <span style={{ position: "absolute", top: 2, right: 3, fontSize: ".5rem", color }}>▲</span>}
                                    <div style={{ fontSize: ".7rem" }}>{SRC_ICONS[src]}</div>
                                    <div style={{ fontFamily: "var(--font-mono)", fontSize: ".72rem", fontWeight: 700, color }}>
                                        {val.toFixed(1)}
                                    </div>
                                </button>
                            )
                        })}
                    </div>

                    <div style={{ marginBottom: 10 }}>
                        <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: ".56rem", color: "var(--text-3)", marginBottom: 4 }}>
                            <span>{SRC_LABELS[activeSource]}</span>
                            <span>{((selected.sources as Record<string, number>)[activeSource] ?? 0).toFixed(1)} {SRC_UNITS[activeSource]}</span>
                        </div>
                        <Sparkline seed={`${selected.spike_id}:${activeSource}`} color={SRC_COLOR[activeSource]} />
                    </div>

                    <button
                        onClick={() => setCommentsOpen(o => !o)}
                        style={{
                            width: "100%", padding: "8px", borderRadius: "var(--r-md)",
                            background: "var(--accent-dim)", border: "1px solid var(--accent-glow)",
                            color: "var(--accent)", fontSize: ".74rem", fontWeight: 700, cursor: "pointer",
                        }}
                    >
                        💬 {commentsOpen ? "Hide live comments" : "View live comments"}
                    </button>

                    {commentsOpen && <CommentBubbles topic={selected.topic} />}

                    <div style={{ fontFamily: "var(--font-mono)", fontSize: ".56rem", color: "var(--text-3)", marginTop: 8 }}>
                        ID: {selected.spike_id} · Tick {selected.tick}
                    </div>
                </div>
            )}

            <div style={{ padding: "12px 14px 14px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                    <span style={{ fontFamily: "var(--font-mono)", fontSize: ".58rem", textTransform: "uppercase", letterSpacing: ".08em", color: "var(--text-3)" }}>
                        Trending now · {spikeCount} stor{spikeCount !== 1 ? "ies" : "y"}
                    </span>
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                    {trending.map(spike => {
                        const color = severityColor(spike.severity)
                        const isSel = spike.spike_id === selected?.spike_id
                        return (
                            <div
                                key={spike.spike_id}
                                onClick={() => setSelectedId(spike.spike_id)}
                                onDoubleClick={() => { setSelectedId(spike.spike_id); setCommentsOpen(true) }}
                                style={{
                                    background: "var(--bg-2)", border: `1px solid ${isSel ? "var(--accent)" : "var(--border)"}`,
                                    borderRadius: "var(--r-md)", padding: "9px 10px", cursor: "pointer",
                                    transition: "all .15s",
                                }}
                            >
                                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 5 }}>
                                    {isTeamTopic(spike.topic)
                                        ? <Flag team={spike.topic} size="sm" />
                                        : <span style={{ fontSize: ".9rem" }}>🌍</span>}
                                    <span style={{ fontSize: ".72rem", fontWeight: 700, color: "var(--text-1)", flex: 1, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                                        {spike.topic}
                                    </span>
                                    {matchTeams.has(canonTeam(spike.topic)) && (
                                        <span style={{ fontFamily: "var(--font-mono)", fontSize: ".46rem", color: "var(--accent)", border: "1px solid var(--accent-glow)", borderRadius: 3, padding: "0 2px", whiteSpace: "nowrap" }}>MATCH</span>
                                    )}
                                    <span style={{ fontSize: ".76rem", fontWeight: 700, color }}>
                                        {Math.round(spike.severity * 100)}%
                                    </span>
                                </div>
                                <Sparkline seed={spike.spike_id} color={color} />
                                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 4 }}>
                                    <span style={{ fontSize: ".7rem" }}>
                                        {(spike.source_names ?? []).map(s => SRC_ICONS[s] ?? "").join(" ")}
                                    </span>
                                    <span style={{ fontFamily: "var(--font-mono)", fontSize: ".54rem", color: "var(--text-3)" }}>
                                        {new Date(spike.timestamp * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                                    </span>
                                </div>
                            </div>
                        )
                    })}
                </div>
            </div>

        </div>
    )
}