from nhlpy import NHLClient
from datetime import datetime
from zoneinfo import ZoneInfo
from rich.console import Console, Group
from rich.panel import Panel
from rich.live import Live
import time

console = Console()
client = NHLClient()

# Stores goals we've already seen
goal_history = {}


def build_dashboard():

    scores = client.game_center.daily_scores()
    panels = []

    # LIVE first, then scheduled, then final
    games = sorted(
        scores["games"],
        key=lambda g: (
            0 if g["gameState"] == "LIVE"
            else 1 if g["gameState"] not in ["FINAL", "OFF"]
            else 2
        )
    )

    for game in games: 

        away = game["awayTeam"]["abbrev"]
        home = game["homeTeam"]["abbrev"]

        away_score = game["awayTeam"].get("score", 0)
        home_score = game["homeTeam"].get("score", 0)

        away_sog = game["awayTeam"].get("sog", 0)
        home_sog = game["homeTeam"].get("sog", 0)

        state = game["gameState"]

        # Status
        if state == "LIVE":
            period = game.get("period", "")
            clock = game.get("clock", {})

            status = (
                f"[green]P{period} "
                f"{clock.get('timeRemaining', '')}[/green]"
            )

        elif state in ["FINAL", "OFF"]:
            status = "[red]FINAL[/red]"

        else:
            start_time = game.get("startTimeUTC")

            if start_time:
                dt = datetime.fromisoformat(
                    start_time.replace("Z", "+00:00")
                )

                local_time = dt.astimezone(
                    ZoneInfo("America/Phoenix")
                )

                status = (
                    "[cyan]Starts: "
                    + local_time.strftime("%I:%M %p MST")
                    + "[/cyan]"
                )
            else:
                status = "[cyan]Scheduled[/cyan]"

        content = (
            f"{away} {away_score} ({away_sog} SOG)\n"
            f"{home} {home_score} ({home_sog} SOG)\n\n"
            f"{status}"
        )

        # Power Play
        situation = game.get("situation", {})

        try:
            home_strength = situation["homeTeam"]["strength"]
            away_strength = situation["awayTeam"]["strength"]

            if home_strength > away_strength:
                content += (
                    f"\n[yellow]⚡ {home} POWER PLAY[/yellow]"
                )

            elif away_strength > home_strength:
                content += (
                    f"\n[yellow]⚡ {away} POWER PLAY[/yellow]"
                )

        except Exception:
            pass

        # Goal history
        game_id = game["id"]

        if game_id not in goal_history:
            goal_history[game_id] = []

        goals = game.get("goals", [])

        for goal in goals:

            period_num = goal.get(
                "periodDescriptor", {}
            ).get("number", "")

            time_in_period = goal.get(
                "timeInPeriod", ""
            )

            team = goal.get(
                "teamAbbrev",
                ""
            )

            scorer = goal.get(
                "name", {}
            ).get(
                "default",
                "Unknown"
            )

            assists = [
                assist.get("name", {}).get(
                    "default", "Unknown"
                )
                for assist in goal.get(
                    "assists", []
                )
            ]

            assist_text = (
                ", ".join(assists)
                if assists
                else "Unassisted"
            )

            goal_text = (
                f"P{period_num} {time_in_period}"
                f" | {team}"
                f" | {scorer}"
                f" ({assist_text})"
            )

            # Store goal only once
            if goal_text not in goal_history[game_id]:
                goal_history[game_id].append(goal_text)

        # Display stored goals
        if goal_history.get(game_id):
            content += "\n\n[bold]Goals[/bold]"
            for goal_text in goal_history[game_id]:
                content += f"\n{goal_text}"

        panels.append(
            Panel(
                content,
                title=f"{away} @ {home}",
                expand=False
            )
        )

    return Group(*panels)


try:

    with Live(
        build_dashboard(),
        refresh_per_second=1,
        console=console
    ) as live:

        while True:
            live.update(build_dashboard())
            time.sleep(5)

except KeyboardInterrupt:
    console.print(
        "\n[red]Scoreboard stopped.[/red]"
    )