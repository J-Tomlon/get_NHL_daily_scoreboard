#!/usr/bin/env python3
"""NHL live scoreboard dashboard.

Setup:  pip install flask nhl-api-py
Run:    python nhl_dashboard.py
Open:   http://localhost:5000  (from a phone: http://<this-machine's-IP>:5000)

Options (environment variables):
  NHL_TZ    time zone for start times (default America/Phoenix)
  NHL_PORT  port to serve on (default 5000)

Pin a favorite team with ?team=UTA in the URL, or tap any team abbreviation.
"""
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, Response, jsonify
from nhlpy import NHLClient

TZ = ZoneInfo(os.environ.get("NHL_TZ", "America/Phoenix"))
PORT = int(os.environ.get("NHL_PORT", "5000"))
CACHE_SECONDS = 5
LIVE_STATES = {"LIVE", "CRIT"}
FINAL_STATES = {"FINAL", "OFF"}

app = Flask(__name__)
client = NHLClient()
lock = threading.Lock()
cache = {"at": 0.0, "payload": None}
goal_history = {}  # game id -> goals already seen (same idea as the terminal script)


def ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd", 4: "OT", 5: "SO"}.get(n, str(n))


def parse_status(game):
    state = game.get("gameState", "")
    if state in LIVE_STATES:
        clock = game.get("clock") or {}
        label = ordinal(game["period"]) if game.get("period") else ""
        if clock.get("inIntermission"):
            return "live", f"{label} intermission".strip()
        return "live", f"{label} {clock.get('timeRemaining', '')}".strip()
    if state in FINAL_STATES:
        suffix = {4: " / OT", 5: " / SO"}.get(game.get("period"), "")
        return "final", f"Final{suffix}"
    start = game.get("startTimeUTC")
    if start:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(TZ)
        return "scheduled", dt.strftime("%I:%M %p %Z").lstrip("0")
    return "scheduled", "Scheduled"


def power_play(game):
    try:
        home = game["situation"]["homeTeam"]["strength"]
        away = game["situation"]["awayTeam"]["strength"]
    except (KeyError, TypeError):
        return None
    if home > away:
        return game["homeTeam"]["abbrev"]
    if away > home:
        return game["awayTeam"]["abbrev"]
    return None


def collect_goals(game):
    seen = goal_history.setdefault(game["id"], [])
    for goal in game.get("goals", []):
        period = (goal.get("periodDescriptor") or {}).get("number")
        team = goal.get("teamAbbrev", "")
        if isinstance(team, dict):
            team = team.get("default", "")
        entry = {
            "when": f"{ordinal(period)} {goal.get('timeInPeriod', '')}".strip(),
            "team": team,
            "scorer": (goal.get("name") or {}).get("default", "Unknown"),
            "assists": [
                (a.get("name") or {}).get("default", "Unknown")
                for a in goal.get("assists", [])
            ],
        }
        if entry not in seen:
            seen.append(entry)
    return seen


def build_game(game):
    kind, status = parse_status(game)
    away, home = game["awayTeam"], game["homeTeam"]
    return {
        "id": game["id"],
        "kind": kind,
        "status": status,
        "away": {"abbrev": away["abbrev"], "score": away.get("score", 0), "sog": away.get("sog", 0)},
        "home": {"abbrev": home["abbrev"], "score": home.get("score", 0), "sog": home.get("sog", 0)},
        "powerPlay": power_play(game) if kind == "live" else None,
        "goals": collect_goals(game),
    }


def fetch_payload():
    scores = client.game_center.daily_scores()
    order = {"live": 0, "scheduled": 1, "final": 2}
    games = sorted((build_game(g) for g in scores.get("games", [])), key=lambda g: order[g["kind"]])
    now = datetime.now(TZ)
    return {
        "date": now.strftime("%A, %B %d").replace(" 0", " "),
        "updated": now.strftime("%I:%M:%S %p").lstrip("0"),
        "games": games,
        "stale": False,
    }


@app.route("/api/scores")
def api_scores():
    with lock:
        if cache["payload"] is None or time.time() - cache["at"] > CACHE_SECONDS:
            try:
                cache["payload"] = fetch_payload()
            except Exception as exc:
                if cache["payload"] is None:
                    return jsonify({"error": str(exc)}), 502
                cache["payload"]["stale"] = True
            cache["at"] = time.time()
        return jsonify(cache["payload"])


@app.route("/")
def index():
    return Response(PAGE, mimetype="text/html")


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="apple-mobile-web-app-capable" content="yes">
<title>NHL today</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#e9f0f5;--card:#fff;--ink:#10233a;--mute:#5b7088;--line:#cfdbe5;--live:#d1242f;--pp:#a86d00;--fav:#1d5fa8}
@media (prefers-color-scheme:dark){:root{--bg:#0e1a28;--card:#15263a;--ink:#e8f0f7;--mute:#8ba1b8;--line:#26394f;--live:#ff5560;--pp:#f0b429;--fav:#5aa6ee}}
*{box-sizing:border-box}
body{margin:0;padding:20px 16px 40px;background:var(--bg);color:var(--ink);font:500 17px/1.35 "Barlow Condensed","Arial Narrow","Helvetica Neue",sans-serif}
header{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:4px 16px;max-width:1100px;margin:0 auto 16px}
h1{margin:0;font-size:2rem;font-weight:700}
.meta{color:var(--mute)}
.warn{color:var(--live);font-weight:700}
#games{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:14px;max-width:1100px;margin:0 auto}
.game{background:var(--card);border:1px solid var(--line);border-left:5px solid var(--line);border-radius:6px;padding:12px 14px}
.game.live{border-left-color:var(--live)}
.game.fav{outline:2px solid var(--fav);outline-offset:-1px}
.game.final{opacity:.78}
.top{display:flex;justify-content:space-between;color:var(--mute);margin-bottom:6px}
.live .status{color:var(--live);font-weight:700}
.live .status::before{content:"";display:inline-block;width:.55em;height:.55em;border-radius:50%;background:var(--live);margin-right:.45em;animation:pulse 1.4s ease-in-out infinite}
@keyframes pulse{50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){.live .status::before{animation:none}}
.pp{color:var(--pp);font-weight:700}
.row{display:flex;align-items:baseline;gap:10px}
.team{all:unset;cursor:pointer;font-size:1.9rem;font-weight:700;min-width:3.4ch}
.team:focus-visible{outline:2px solid var(--fav);outline-offset:2px}
.sog{flex:1;color:var(--mute)}
.score{font-size:2.6rem;font-weight:700;font-variant-numeric:tabular-nums}
.goals{margin:10px 0 0;padding:8px 0 0;border-top:1px solid var(--line);list-style:none;font-size:.95rem}
.goals li{margin:2px 0}
.goals span{color:var(--mute)}
.empty{grid-column:1/-1;text-align:center;color:var(--mute);padding:40px 0}
</style>
</head>
<body>
<header>
  <div><h1>NHL today</h1><div class="meta" id="date"></div></div>
  <div class="meta" id="updated"></div>
</header>
<main id="games"><p class="empty">Loading scores…</p></main>
<script>
const params = new URLSearchParams(location.search);
let fav = (params.get("team") || "").toUpperCase();
let last = null;
const esc = s => String(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const isFav = g => fav && (g.away.abbrev === fav || g.home.abbrev === fav);

function teamRow(t, kind) {
  const score = kind === "scheduled" ? "–" : t.score;
  const shots = kind === "scheduled" ? "" : t.sog + " shots";
  return `<div class="row"><button class="team" data-team="${esc(t.abbrev)}">${esc(t.abbrev)}</button><span class="sog">${shots}</span><span class="score">${score}</span></div>`;
}

function goalList(goals) {
  if (!goals.length) return "";
  const items = goals.map(g => {
    const assists = g.assists.length ? g.assists.join(", ") : "Unassisted";
    return `<li><b>${esc(g.when)}</b> ${esc(g.team)} ${esc(g.scorer)} <span>(${esc(assists)})</span></li>`;
  }).join("");
  return `<ol class="goals">${items}</ol>`;
}

function card(g) {
  const pp = g.powerPlay ? `<span class="pp">Power play: ${esc(g.powerPlay)}</span>` : "";
  return `<article class="game ${g.kind}${isFav(g) ? " fav" : ""}">
    <div class="top"><span class="status">${esc(g.status)}</span>${pp}</div>
    ${teamRow(g.away, g.kind)}${teamRow(g.home, g.kind)}${goalList(g.goals)}
  </article>`;
}

function render() {
  if (!last) return;
  document.getElementById("date").textContent = last.date;
  document.getElementById("updated").innerHTML = last.stale
    ? '<span class="warn">Can\'t reach the NHL feed. Showing the last scores.</span>'
    : "Updated " + esc(last.updated);
  const games = last.games.slice().sort((a, b) => isFav(b) - isFav(a));
  document.getElementById("games").innerHTML = games.length
    ? games.map(card).join("") : '<p class="empty">No games today.</p>';
}

async function load() {
  try {
    const r = await fetch("/api/scores");
    if (!r.ok) throw new Error(r.status);
    last = await r.json();
    render();
  } catch (e) {
    if (last) { last.stale = true; render(); }
    else document.getElementById("games").innerHTML =
      '<p class="empty">Can\'t load scores. Check that the server has internet access.</p>';
  }
}

document.getElementById("games").addEventListener("click", e => {
  const btn = e.target.closest("[data-team]");
  if (!btn) return;
  fav = fav === btn.dataset.team ? "" : btn.dataset.team;
  history.replaceState(null, "", fav ? "?team=" + fav : location.pathname);
  render();
});

load();
setInterval(load, 5000);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    # host 0.0.0.0 lets other devices on your network (your phone) connect.
    app.run(host="0.0.0.0", port=PORT)
