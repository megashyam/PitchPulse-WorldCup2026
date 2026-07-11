// types/predict.ts — updated with group finishing position fields

export interface StageProbability {
    p: number
    ci_lo: number
    ci_hi: number
}

export interface TeamPrediction {
    name: string
    group: string
    elo: number
    fifa_rank: number


    group_exit: StageProbability
    group_first: StageProbability
    group_second: StageProbability
    group_third: StageProbability

    group_fourth: StageProbability


    // Knockout stages
    r32: StageProbability
    r16: StageProbability
    qf: StageProbability
    sf: StageProbability
    final: StageProbability
    champion: StageProbability
}

export interface TournamentPrediction {
    sim_id: string
    n_sims: number
    elapsed_s: number
    run_at: string
    teams: TeamPrediction[]
    status: "complete" | "running" | "error"
}

export interface SimStatus {
    status: "idle" | "running" | "complete" | "error"
    sim_id?: string
    started_at?: string
    error?: string
}

export const STAGES = ["r32", "r16", "qf", "sf", "final", "champion"] as const
export type Stage = (typeof STAGES)[number]

export const STAGE_LABELS: Record<Stage, string> = {
    r32: "R32",
    r16: "R16",
    qf: "QF",
    sf: "SF",
    final: "Final",
    champion: "Champion",
}