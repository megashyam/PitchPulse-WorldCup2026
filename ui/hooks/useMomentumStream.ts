"use client"

/**
 * Fetch and stream the live momentum snapshot for a fixture.
 *
 * Momentum is a live-only concept, so the hook loads once from REST for an
 * immediate paint and then subscribes to SSE only when the fixture is known
 * to be live. Non-live fixtures intentionally normalize to null instead of
 * being treated as errors.
 */

import { useEffect, useState } from "react"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
const LIVE = new Set(["1H", "HT", "2H", "ET", "P"])

export interface TeamMomentumData {
    momentum_score: number
    goal_prob_5min: number
    ewma_possession: number
    ewma_pressure: number
    ewma_pass_acc: number
    bump: number
}

export interface MomentumSnapshot {
    fixture_id: number
    home_name: string
    away_name: string
    elapsed: number | null
    home: TeamMomentumData
    away: TeamMomentumData
    updated_at: string
}

interface UseMomentumStreamResult {
    momentum: MomentumSnapshot | null
    isWaiting: boolean
    error: string | null
}

function normalize(data: any): MomentumSnapshot | null {
    if (!data || data.status === "not_started") return null
    return data as MomentumSnapshot
}

export function useMomentumStream(
    fixtureId: string,
    statusShort?: string,
): UseMomentumStreamResult {
    const [momentum, setMomentum] = useState<MomentumSnapshot | null>(null)
    const [isWaiting, setWaiting] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const knownNotLive = statusShort !== undefined && !LIVE.has(statusShort)

    useEffect(() => {
        if (!fixtureId) return
        let mounted = true

        fetch(`${API}/matches/${fixtureId}/momentum`)
            .then(r => (r.ok ? r.json() : null))
            .then(data => {
                if (mounted) setMomentum(normalize(data))
            })
            .catch(() => { })

        if (knownNotLive) return () => { mounted = false }

        const es = new EventSource(`${API}/matches/${fixtureId}/momentum/stream`)

        es.addEventListener("momentum_update", (e: MessageEvent) => {
            if (!mounted) return
            try {
                setMomentum(JSON.parse(e.data) as MomentumSnapshot)
                setWaiting(false)
                setError(null)
            } catch {
                setError("Failed to parse momentum update")
            }
        })

        es.addEventListener("waiting", () => {
            if (mounted) setWaiting(true)
        })

        es.onerror = () => { }

        return () => {
            mounted = false
            es.close()
        }
    }, [fixtureId, knownNotLive])

    return { momentum, isWaiting, error }
}