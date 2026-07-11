"use client"

/**
 * Load the tactical fingerprint match for a fixture.
 *
 * Tactical fingerprints are slow-moving, cached server-side, and stored in
 * Weaviate, so a straightforward REST fetch is enough here. The hook
 * normalizes the "not started" and "missing fingerprint" cases to null so
 * the card can render its fallback state without branching on transport
 * details.
 */

import { useEffect, useState } from "react"

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

export interface FingerprintMatch {
    team: string
    opponent: string
    competition: string
    season: string
    match_pct: number | null
    ppda: number
    ppda_mid_third: number
    ppda_att_third: number
    possession: number
    press_intensity: number
    content: string
}

export interface TeamFingerprint {
    team: string
    opponent: string
    live_possession: number
    match: FingerprintMatch
    alternatives: {
        team: string
        season: string
        ppda: number
        match_pct: number | null
    }[]
}

export interface TacticalData {
    fixture_id: number
    home_name: string
    away_name: string
    home: TeamFingerprint | null
    away: TeamFingerprint | null
    source: string
    generated_at: string
}

function normalize(data: any): TacticalData | null {
    if (!data || data.status === "not_started" || data.status === "pending") return null
    return data as TacticalData
}

export function useTactical(fixtureId: string) {
    const [tactical, setTactical] = useState<TacticalData | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        if (!fixtureId) return
        let mounted = true
        setLoading(true)

        fetch(`${API}/matches/${fixtureId}/tactical`)
            .then(r => (r.ok ? r.json() : null))
            .then(data => {
                if (mounted) {
                    setTactical(normalize(data))
                    setLoading(false)
                }
            })
            .catch(() => {
                if (mounted) setLoading(false)
            })

        const t = setInterval(() => {
            fetch(`${API}/matches/${fixtureId}/tactical`)
                .then(r => (r.ok ? r.json() : null))
                .then(data => {
                    if (mounted) setTactical(normalize(data))
                })
                .catch(() => { })
        }, 60_000)

        return () => {
            mounted = false
            clearInterval(t)
        }
    }, [fixtureId])

    return { tactical, loading }
}