"use client"

/**
 * Stream live match intelligence narratives and keep the empty-state logic honest.
 *
 * The backend may legitimately have no intel for a non-live or scoreless
 * fixture, so the hook treats a successful empty fetch as a real idle state
 * rather than a failure. Live fixtures keep both polling and SSE enabled;
 * completed fixtures only use the initial fetch because their intel history
 * stops changing.
 */

import { useEffect, useRef, useState, useCallback } from "react"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const POLL_INTERVAL = 30_000

const LIVE = new Set(["1H", "HT", "2H", "ET", "P"])
const COMPLETED = new Set(["FT", "AET", "PEN"])

export interface IntelEntry {
    fixture_id: number
    minute: number
    narration_type: "tactical" | "event_reaction" | "xg_divergence"
    narrative: string
    score: number
    rag_docs_used: number
    via: "mistral" | "groq" | "template"
    updated_at: string
    event_sig?: string
}

export type IntelPhase = "loading" | "streaming" | "idle_notlive" | "idle_nodata"

interface UseIntelStreamResult {
    entries: IntelEntry[]
    isWaiting: boolean       // kept for back-compat; true only during first load
    phase: IntelPhase
    error: string | null
}

function dedupeKey(e: IntelEntry): string {
    return e.event_sig ?? `min:${e.minute}:${e.narration_type}`
}

function sortedDeduped(entries: IntelEntry[]): IntelEntry[] {
    const byKey = new Map<string, IntelEntry>()
    for (const e of entries) {
        const key = dedupeKey(e)
        const existing = byKey.get(key)
        if (!existing || e.updated_at > existing.updated_at) byKey.set(key, e)
    }
    return Array.from(byKey.values())
        .sort((a, b) => b.minute - a.minute)
        .slice(0, 30)
}

export function useIntelStream(
    fixtureId: string,
    statusShort?: string,
): UseIntelStreamResult {
    const [entries, setEntries] = useState<IntelEntry[]>([])
    const [firstLoadDone, setFirstLoadDone] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const mountedRef = useRef(true)
    // Keep the completed-match poll cap off the React dependency list so a
    // new fetch does not tear down the SSE/poll setup on every update.
    const entriesCountRef = useRef(0)

    const isLive = statusShort ? LIVE.has(statusShort) : false
    const isCompleted = statusShort ? COMPLETED.has(statusShort) : false

    const fetchFeed = useCallback(async () => {
        if (!fixtureId) return
        try {
            const r = await fetch(`${API}/matches/${fixtureId}/intel`)
            if (r.ok) {
                const data: { entries?: IntelEntry[] } = await r.json()
                if (!mountedRef.current) return
                const list = Array.isArray(data?.entries) ? data.entries : []
                const deduped = sortedDeduped(list)
                setEntries(deduped)
                entriesCountRef.current = deduped.length
                setError(null)
            }
        } catch (e) {
            // Network issues are transient here; the next poll or SSE event retries.
        } finally {
            if (mountedRef.current) setFirstLoadDone(true)
        }
    }, [fixtureId])

    useEffect(() => {
        if (!fixtureId) return
        mountedRef.current = true
        setFirstLoadDone(false)
        entriesCountRef.current = 0

        fetchFeed()

        if (!isLive && !isCompleted) {
            return () => { mountedRef.current = false }
        }

        let ftPolls = 0
        const FT_FAST_POLLS = 6       // ~3 min at the normal 30s cadence...
        const FT_SLOW_INTERVAL_MS = 120_000  // ...then every 2 min after that, forever
        let poll: ReturnType<typeof setInterval> = setInterval(tick, POLL_INTERVAL)

        function tick() {
            if (isCompleted) {
                if (entriesCountRef.current > 0) {
                    clearInterval(poll)
                    return
                }
                ftPolls += 1
                if (ftPolls === FT_FAST_POLLS) {
                    clearInterval(poll)
                    poll = setInterval(tick, FT_SLOW_INTERVAL_MS)
                }
            }
            fetchFeed()
        }

        let es: EventSource | null = null
        if (isLive) {
            es = new EventSource(`${API}/matches/${fixtureId}/intel/stream`)
            es.addEventListener("intel_update", () => {
                if (mountedRef.current) fetchFeed()
            })
            es.onerror = () => { }
        }

        return () => {
            mountedRef.current = false
            clearInterval(poll)
            if (es) es.close()
        }
        // Only resubscribe when the fixture identity or live/completed state changes.
    }, [fixtureId, isLive, isCompleted, fetchFeed])

    let phase: IntelPhase
    if (entries.length > 0) phase = "streaming"
    else if (!firstLoadDone) phase = "loading"
    else if (isLive) phase = "idle_nodata"
    else if (isCompleted) phase = "idle_nodata"
    else phase = "idle_notlive"

    return {
        entries,
        isWaiting: !firstLoadDone,
        phase,
        error,
    }
}