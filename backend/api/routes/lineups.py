"""Lineup routes for fixture starting XIs and player photos.

The lineup endpoint uses a tiered data strategy: Zafronix rosters first,
API-Sports live lineups second, a StatsBomb proxy XI third, and a formation
estimate as the final fallback. Photos are resolved independently.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Request

from api.schemas.schema import MatchState

router = APIRouter()
log = logging.getLogger(__name__)

API_KEY = os.getenv("API_SPORTS_KEY", "")
BASE_URL = "https://v3.football.api-sports.io"
SB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

ZAFRONIX_KEY = os.getenv("ZAFRONIX_API_KEY", "")
ZAFRONIX_BASE = "https://api.zafronix.com/fifa/worldcup/v1"
ZAFRONIX_SEASON = int(os.getenv("ZAFRONIX_SEASON", "2026"))

PHOTO_CACHE_TTL = 7 * 86_400
PHOTO_LOOKUP_TIMEOUT = 4.0
ROSTER_CACHE_TTL = 6 * 3600

_POS_LINE = {"GK": 0, "DF": 1, "MF": 2, "FW": 3}


def _estimate_formation(ppda: float, is_home: bool) -> str:
    if ppda < 8:
        return "4-3-3" if is_home else "4-2-3-1"
    if ppda < 14:
        return "4-3-3" if is_home else "4-4-2"
    return "5-3-2" if is_home else "4-5-1"


def _formation_from_counts(n_def: int, n_mid: int, n_fwd: int) -> str:
    """Map defender, midfield, and forward counts to a known formation."""
    key = (n_def, n_mid, n_fwd)
    known = {
        (4, 3, 3): "4-3-3",
        (4, 4, 2): "4-4-2",
        (4, 5, 1): "4-1-4-1",
        (3, 5, 2): "3-5-2",
        (5, 3, 2): "5-3-2",
        (3, 4, 3): "3-4-3",
        (4, 1, 5): "4-2-3-1",
    }
    if key in known:
        return known[key]
    return {3: "3-4-3", 4: "4-3-3", 5: "5-3-2"}.get(n_def, "4-3-3")


async def _photo_for(r, client: httpx.AsyncClient, name: str) -> str | None:
    """Return a cached Wikipedia thumbnail URL for a player name."""
    if not name:
        return None
    cache_key = f"player:photo:{name.lower()}"
    cached = await r.get(cache_key)
    if cached is not None:
        return cached or None

    url = (
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(name)}"
    )
    photo = ""
    try:
        resp = await client.get(url, timeout=PHOTO_LOOKUP_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            thumb = data.get("thumbnail") or {}
            if thumb.get("source") and thumb.get("width", 0) >= 80:
                photo = thumb["source"]
    except Exception:
        pass

    await r.setex(cache_key, PHOTO_CACHE_TTL, photo)
    return photo or None


_ZAFRONIX_NAME_ALIAS = {
    "USA": "United States",
    "United States of America": "United States",
    "Korea Republic": "South Korea",
    "Korea DPR": "North Korea",
    "IR Iran": "Iran",
    "Iran (Islamic Republic)": "Iran",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "China PR": "China",
    "Czechia": "Czech Republic",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Cabo Verde": "Cape Verde",
}


def _zafronix_name(team_name: str) -> str:
    return _ZAFRONIX_NAME_ALIAS.get(team_name, team_name)


def _norm_team(name: str) -> str:
    """Normalize team names for cross-source comparison."""
    n = _ZAFRONIX_NAME_ALIAS.get(name, name)
    return "".join(ch for ch in n.lower() if ch.isalnum())


async def _fetch_zafronix_roster(
    client: httpx.AsyncClient, team_name: str
) -> tuple[list[dict] | None, str]:
    """Fetch one Zafronix roster and return a failure reason if needed."""
    candidates = []
    aliased = _zafronix_name(team_name)
    candidates.append(aliased)
    if team_name != aliased:
        candidates.append(team_name)

    last_reason = "unknown"
    for name in candidates:
        url = f"{ZAFRONIX_BASE}/teams/{urllib.parse.quote(name)}/roster"
        try:
            resp = await client.get(
                url,
                params={"year": ZAFRONIX_SEASON},
                headers={"X-API-Key": ZAFRONIX_KEY},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list) and len(data) >= 11:
                    return data, "ok"
                n = len(data) if isinstance(data, list) else 0
                last_reason = f"200 OK but only {n} players for '{name}' (year={ZAFRONIX_SEASON}) — 2026 squad may not be populated in Zafronix yet"
                log.info(f"Zafronix roster '{name}': {last_reason}")
            elif resp.status_code == 404:
                last_reason = f"404 for '{name}' — team name doesn't match Zafronix's naming (try adding it to _ZAFRONIX_NAME_ALIAS)"
                log.info(f"Zafronix roster: {last_reason}")
            elif resp.status_code in (401, 403):
                last_reason = f"{resp.status_code} — ZAFRONIX_API_KEY is missing, invalid, or expired"
                log.warning(f"Zafronix roster: {last_reason}")
                return None, last_reason
            else:
                last_reason = f"HTTP {resp.status_code} for '{name}'"
                log.info(f"Zafronix roster: {last_reason}")
        except Exception as exc:
            last_reason = f"request failed: {exc}"
            log.warning(f"Zafronix roster fetch failed for '{name}': {exc}")

    return None, last_reason


def _select_starting_xi(roster: list[dict]) -> tuple[list[dict], str]:
    """Pick a plausible starting XI from a squad and infer a formation."""

    def sort_key(p: dict):
        return (
            0 if p.get("starter") else 1,
            0 if p.get("captain") else 1,
            p.get("jersey") or 99,
        )

    _TARGET_SHAPES = [
        (4, 3, 3),
        (4, 4, 2),
        (3, 5, 2),
        (5, 3, 2),
        (3, 4, 3),
    ]

    keepers = sorted([p for p in roster if p.get("position") == "GK"], key=sort_key)
    defs = sorted([p for p in roster if p.get("position") == "DF"], key=sort_key)
    mids = sorted([p for p in roster if p.get("position") == "MF"], key=sort_key)
    fwds = sorted([p for p in roster if p.get("position") == "FW"], key=sort_key)

    n_def, n_mid, n_fwd = 4, 3, 3
    for d, m, f in _TARGET_SHAPES:
        if len(defs) >= d and len(mids) >= m and len(fwds) >= f:
            n_def, n_mid, n_fwd = d, m, f
            break
    else:
        n_def = min(len(defs), 5) or 4
        n_mid = min(len(mids), 5) or 3
        n_fwd = min(len(fwds), 3) or 3

    xi: list[dict] = []
    if keepers:
        xi.append(keepers[0])

    xi.extend(defs[:n_def])
    xi.extend(mids[:n_mid])
    xi.extend(fwds[:n_fwd])

    if len(xi) < 11:
        leftover = [p for p in (defs + mids + fwds) if p not in xi]
        xi.extend(leftover[: 11 - len(xi)])

    n_def = sum(1 for p in xi if p.get("position") == "DF")
    n_mid = sum(1 for p in xi if p.get("position") == "MF")
    n_fwd = sum(1 for p in xi if p.get("position") == "FW")
    formation = _formation_from_counts(n_def or 4, n_mid or 3, n_fwd or 3)
    return xi, formation


async def _build_zafronix_team(
    r, client: httpx.AsyncClient, photo_client: httpx.AsyncClient, team_name: str
) -> tuple[dict | None, str]:
    roster, reason = await _fetch_zafronix_roster(client, team_name)
    if not roster:
        return None, reason

    xi, formation = _select_starting_xi(roster)
    names = [p.get("name") or "" for p in xi]
    photos = await asyncio.gather(
        *[_photo_for(r, photo_client, n) for n in names],
        return_exceptions=True,
    )

    starting = []
    for p, photo in zip(xi, photos):
        starting.append(
            {
                "number": p.get("jersey") or 0,
                "name": p.get("name") or "",
                "position": p.get("position") or "",
                "grid": "",
                "captain": bool(p.get("captain")),
                "photo": photo if isinstance(photo, str) else None,
            }
        )

    return {
        "team": team_name,
        "formation": formation,
        "startingXI": starting,
        "coach": None,
    }, "ok"


async def _fetch_from_zafronix(
    r, home_name: str, away_name: str
) -> tuple[dict | None, str]:
    if not ZAFRONIX_KEY:
        return None, "ZAFRONIX_API_KEY is not set in this process's environment"
    cache_key = f"zafronix:lineup:{home_name}:{away_name}"
    cached = await r.get(cache_key)
    if cached:
        return json.loads(cached), "ok (cached)"

    async with httpx.AsyncClient() as client, httpx.AsyncClient(
        headers={"User-Agent": "wc2026-lineups/1.0"}
    ) as photo_client:
        (home_entry, home_reason), (away_entry, away_reason) = await asyncio.gather(
            _build_zafronix_team(r, client, photo_client, home_name),
            _build_zafronix_team(r, client, photo_client, away_name),
        )

    if not home_entry or not away_entry:
        reason = f"home({home_name})={home_reason} · away({away_name})={away_reason}"
        log.info(f"Zafronix lineup unavailable: {reason}")
        return None, reason

    result = {"home": home_entry, "away": away_entry, "source": "zafronix"}
    await r.setex(cache_key, ROSTER_CACHE_TTL, json.dumps(result))
    return result, "ok"


def _parse_player(raw: dict) -> dict:
    pl = raw.get("player", {})
    stats = raw.get("statistics", [{}])
    games = stats[0].get("games", {}) if stats else {}
    player_id = pl.get("id")
    return {
        "number": pl.get("number") or 0,
        "name": pl.get("name") or "",
        "position": pl.get("pos") or "",
        "grid": games.get("number") or "",
        "photo": (
            f"https://media.api-sports.io/football/players/{player_id}.png"
            if player_id
            else None
        ),
    }


async def _fetch_from_api_sports(fixture_id: str) -> dict | None:
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{BASE_URL}/fixtures/lineups",
                headers={"x-apisports-key": API_KEY},
                params={"fixture": fixture_id},
                timeout=12,
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        log.warning(f"lineup fetch failed: {exc}")
        return None

    response = data.get("response", [])
    if len(response) < 2:
        return None

    result = {}
    for entry in response[:2]:
        team = entry.get("team", {})
        result[team.get("id")] = {
            "team": team.get("name", ""),
            "formation": entry.get("formation", "4-3-3"),
            "startingXI": [_parse_player(p) for p in entry.get("startXI", [])],
            "coach": (entry.get("coach") or {}).get("name", ""),
        }
    return result if len(result) == 2 else None


_SB_FORMATION_MAP = {
    433: "4-3-3",
    442: "4-4-2",
    4231: "4-2-3-1",
    352: "3-5-2",
    532: "5-3-2",
    4141: "4-1-4-1",
    343: "3-4-3",
    3421: "3-4-2-1",
    4213: "4-2-3-1",
    41212: "4-1-4-1",
    4411: "4-4-2",
    4321: "4-3-3",
}


def _sb_formation_to_string(code: int | None) -> str:
    if code and code in _SB_FORMATION_MAP:
        return _SB_FORMATION_MAP[code]
    first = int(str(code)[0]) if code else 4
    return {3: "3-4-3", 4: "4-3-3", 5: "5-3-2"}.get(first, "4-3-3")


async def _fetch_statsbomb_proxy_lineup(r, match_id: int) -> dict | None:
    cache_key = f"sb:lineup:{match_id}"
    cached = await r.get(cache_key)
    if cached:
        return json.loads(cached)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{SB_BASE}/events/{match_id}.json", timeout=20)
            resp.raise_for_status()
            events = resp.json()
    except Exception as exc:
        log.warning(f"StatsBomb proxy lineup fetch failed for mid={match_id}: {exc}")
        return None

    xi_events = [e for e in events if e.get("type", {}).get("name") == "Starting XI"]
    if len(xi_events) < 2:
        return None

    result: dict[str, dict] = {}
    async with httpx.AsyncClient(
        headers={"User-Agent": "wc2026-lineups/1.0"}
    ) as photo_client:
        for ev in xi_events[:2]:
            team_name = ev.get("team", {}).get("name", "")
            tactics = ev.get("tactics", {})
            lineup_sorted = sorted(
                tactics.get("lineup", []),
                key=lambda p: (p.get("position", {}).get("id") or 99),
            )
            names = [(p.get("player", {}).get("name") or "") for p in lineup_sorted]
            photos = await asyncio.gather(
                *[_photo_for(r, photo_client, n) for n in names],
                return_exceptions=True,
            )
            starting = []
            for p, photo in zip(lineup_sorted, photos):
                player = p.get("player", {})
                starting.append(
                    {
                        "number": p.get("jersey_number") or 0,
                        "name": player.get("name") or "",
                        "position": p.get("position", {}).get("name") or "",
                        "grid": "",
                        "photo": photo if isinstance(photo, str) else None,
                    }
                )
            result[team_name] = {
                "team": team_name,
                "formation": _sb_formation_to_string(tactics.get("formation")),
                "startingXI": starting,
                "coach": None,
            }

    if len(result) < 2:
        return None
    await r.setex(cache_key, 6 * 3600, json.dumps(result))
    return result


@router.get("/{fixture_id}/lineups")
async def lineups(fixture_id: str, request: Request):
    r = request.app.state.redis

    raw = await r.get(f"match:{fixture_id}:state")
    if not raw:
        raise HTTPException(404, "Fixture not found")

    state = MatchState.model_validate_json(raw)

    zx, zx_reason = await _fetch_from_zafronix(r, state.home_name, state.away_name)
    if zx:
        return zx

    if API_KEY:
        api_data = await _fetch_from_api_sports(str(state.fixture_id))
        if api_data:
            teams = list(api_data.values())
            home_entry = next(
                (t for t in teams if t["team"] == state.home_name), teams[0]
            )
            away_entry = next(
                (t for t in teams if t["team"] == state.away_name), teams[1]
            )
            return {"home": home_entry, "away": away_entry, "source": "api-sports"}

    if state.stats_proxy_match_id:
        sb_data = await _fetch_statsbomb_proxy_lineup(r, state.stats_proxy_match_id)
        if sb_data:
            sb_team_names = {_norm_team(t) for t in sb_data.keys()}
            live_names = {_norm_team(state.home_name), _norm_team(state.away_name)}
            if sb_team_names & live_names:
                teams = list(sb_data.values())

                def _match_entry(live_name: str):
                    for entry in teams:
                        if _norm_team(entry["team"]) == _norm_team(live_name):
                            return entry
                    return None

                home_entry = _match_entry(state.home_name)
                away_entry = _match_entry(state.away_name)
                if home_entry and away_entry:
                    return {
                        "home": home_entry,
                        "away": away_entry,
                        "source": "statsbomb_proxy",
                    }
            else:
                log.info(
                    f"[{fixture_id}] StatsBomb proxy match teams {sb_team_names} "
                    f"don't match live teams {live_names} — skipping to estimated "
                    f"formation rather than showing wrong players"
                )

    tac_raw = await r.get(f"match:{fixture_id}:tactical")
    home_ppda, away_ppda = 10.0, 12.0
    if tac_raw:
        try:
            tac = json.loads(tac_raw)
            home_ppda = tac.get("home", {}).get("match", {}).get("ppda", 10.0)
            away_ppda = tac.get("away", {}).get("match", {}).get("ppda", 12.0)
        except Exception:
            pass

    return {
        "home": {
            "team": state.home_name,
            "formation": _estimate_formation(home_ppda, True),
            "startingXI": [],
            "coach": None,
        },
        "away": {
            "team": state.away_name,
            "formation": _estimate_formation(away_ppda, False),
            "startingXI": [],
            "coach": None,
        },
        "source": "estimated",
        "zafronix_debug": zx_reason,
    }
