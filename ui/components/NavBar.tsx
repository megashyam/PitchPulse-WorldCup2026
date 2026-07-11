"use client"

/**
 * Global navigation shell for the app.
 *
 * The nav keeps the dashboard entry point prominent, exposes the theme
 * toggle, and renders a live clock so the interface always has a clear
 * sense of recency while users move between live match views.
 */

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useState } from "react"
import { ThemeToggle } from "@/components/ThemeToggle"

const TABS = [
    { href: "/", label: "Match Dashboard" },
]

export function NavBar() {
    const pathname = usePathname()
    const [time, setTime] = useState("")

    useEffect(() => {
        const tick = () => setTime(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }))
        tick()
        const t = setInterval(tick, 1000)
        return () => clearInterval(t)
    }, [])

    const isActive = (href: string) =>
        href === "/" ? pathname === "/" || pathname.startsWith("/match") : pathname.startsWith(href)

    return (
        <div className="wc-navbar">
            <div className="wc-navbar-left">
                <Link href="/" className="wc-navbar-logo">
                    <span className="wc-navbar-logo-dot" />
                    WC 2026
                </Link>
                <nav className="wc-navbar-tabs">
                    {TABS.map(t => (
                        <Link
                            key={t.href}
                            href={t.href}
                            className={`wc-navbar-tab${isActive(t.href) ? " active" : ""}`}
                        >
                            {t.label}
                        </Link>
                    ))}
                </nav>
            </div>
            <div className="wc-navbar-right">
                <ThemeToggle />
                <span className="wc-navbar-clock">{time}</span>
            </div>
        </div>
    )
}