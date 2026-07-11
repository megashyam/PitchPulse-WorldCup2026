

const CODES: Record<string, string> = {
    // CONCACAF
    "United States": "us", "USA": "us", "Mexico": "mx", "Canada": "ca", "Honduras": "hn",
    "Guatemala": "gt", "El Salvador": "sv", "Costa Rica": "cr", "Panama": "pa", "Jamaica": "jm",
    "Trinidad and Tobago": "tt", "Haiti": "ht", "Curacao": "cw", "Curaçao": "cw",
    // CONMEBOL
    "Brazil": "br", "Argentina": "ar", "Colombia": "co", "Uruguay": "uy", "Chile": "cl",
    "Ecuador": "ec", "Peru": "pe", "Venezuela": "ve", "Bolivia": "bo", "Paraguay": "py",
    // UEFA
    "France": "fr", "Germany": "de", "Spain": "es", "England": "gb-eng", "Portugal": "pt",
    "Netherlands": "nl", "Belgium": "be", "Italy": "it", "Croatia": "hr", "Serbia": "rs",
    "Switzerland": "ch", "Denmark": "dk", "Austria": "at", "Poland": "pl", "Ukraine": "ua",
    "Türkiye": "tr", "Turkiye": "tr", "Turkey": "tr", "Hungary": "hu", "Slovakia": "sk",
    "Czech Republic": "cz", "Czechia": "cz", "Romania": "ro", "Albania": "al", "Slovenia": "si",
    "Georgia": "ge", "Scotland": "gb-sct", "Wales": "gb-wls", "Norway": "no", "Sweden": "se",
    "Iceland": "is", "Finland": "fi", "Greece": "gr", "Ireland": "ie",
    // CAF
    "Morocco": "ma", "Senegal": "sn", "Nigeria": "ng", "Ghana": "gh", "Cameroon": "cm",
    "Ivory Coast": "ci", "Côte d'Ivoire": "ci", "Cote d'Ivoire": "ci", "Algeria": "dz",
    "Tunisia": "tn", "Egypt": "eg", "South Africa": "za", "Mali": "ml", "DR Congo": "cd",
    "Democratic Republic of the Congo": "cd", "Zambia": "zm", "Guinea": "gn",
    "Cape Verde": "cv", "Burkina Faso": "bf", "Angola": "ao",
    // AFC
    "Japan": "jp", "South Korea": "kr", "Korea Republic": "kr", "Australia": "au", "Iran": "ir",
    "IR Iran": "ir", "Saudi Arabia": "sa", "Qatar": "qa", "Iraq": "iq", "Uzbekistan": "uz",
    "Jordan": "jo", "UAE": "ae", "United Arab Emirates": "ae", "Indonesia": "id",
    "New Zealand": "nz", "Oman": "om", "Bahrain": "bh", "China PR": "cn", "China": "cn",
}

export function flagUrl(teamName: string, size: "20" | "40" | "80" | "160" = "80"): string | null {
    const code = CODES[teamName]
    if (!code) return null
    return `https://flagcdn.com/w${size}/${code}.png`
}

export function flagCode(teamName: string): string | null {
    return CODES[teamName] ?? null
}

// Team primary colors for accents/glows
const TEAM_COLORS: Record<string, string> = {
    "Brazil": "#fce803", "Argentina": "#6cb4ee", "France": "#0055a4", "Germany": "#000000",
    "Spain": "#c60b1e", "England": "#ffffff", "Portugal": "#006600", "Netherlands": "#ff6600",
    "Belgium": "#fdda24", "Italy": "#0066cc", "Croatia": "#ff0000", "Mexico": "#006847",
    "United States": "#3c3b6e", "Morocco": "#c1272d", "Japan": "#bc002d", "South Korea": "#003478",
    "Uruguay": "#5cbfeb", "Colombia": "#fcd116", "Senegal": "#00853f", "Ghana": "#006b3f",
}
export function teamColor(teamName: string): string {
    return TEAM_COLORS[teamName] ?? "#4f86f7"
}