"use client"

/**
 * Theme toggle button.
 *
 * The button defers rendering until the client has mounted so it can avoid a
 * flash of the wrong icon while the persisted theme is being read.
 */

import { useTheme } from "@/hooks/useTheme"

export function ThemeToggle() {
    const { theme, toggleTheme, mounted } = useTheme()

    if (!mounted) return <div style={{ width: 30, height: 30 }} />

    return (
        <button
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            title={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            style={{
                width: 30, height: 30, borderRadius: "50%",
                background: "var(--bg-3)", border: "1px solid var(--border)",
                display: "flex", alignItems: "center", justifyContent: "center",
                cursor: "pointer", fontSize: "1rem", transition: "all .15s",
                color: "var(--text-2)",
            }}
            onMouseEnter={e => { e.currentTarget.style.background = "var(--bg-4)"; e.currentTarget.style.color = "var(--text-1)" }}
            onMouseLeave={e => { e.currentTarget.style.background = "var(--bg-3)"; e.currentTarget.style.color = "var(--text-2)" }}
        >
            {theme === "dark" ? "☀️" : "🌙"}
        </button>
    )
}