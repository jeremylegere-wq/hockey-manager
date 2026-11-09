"""Build a demo league, play the full season, print standings and one replayable box score."""
import os
import sys

import db
import seed_demo
import sim

PATH = sys.argv[1] if len(sys.argv) > 1 else "hockeysim.db"
if os.path.exists(PATH):
    os.remove(PATH)

conn = db.connect(PATH)
db.init_schema(conn)
seed_demo.seed(conn)

days = 0
while sim.season_has_games_left(conn):
    sim.sim_day(conn)
    days += 1
print(f"Season complete in {days} simulated days.\n")

print(f"{'Team':<18}{'GP':>4}{'W':>4}{'L':>4}{'OTL':>5}{'PTS':>5}{'GF':>5}{'GA':>5}")
rows = conn.execute("""
    SELECT t.name,
      COUNT(*) gp,
      SUM(CASE WHEN (g.home_team_id=t.team_id AND g.home_goals>g.away_goals) OR
                    (g.away_team_id=t.team_id AND g.away_goals>g.home_goals) THEN 1 ELSE 0 END) w,
      SUM(CASE WHEN g.went_to_ot=1 AND ((g.home_team_id=t.team_id AND g.home_goals<g.away_goals) OR
                    (g.away_team_id=t.team_id AND g.away_goals<g.home_goals)) THEN 1 ELSE 0 END) otl,
      SUM(CASE WHEN g.home_team_id=t.team_id THEN g.home_goals ELSE g.away_goals END) gf,
      SUM(CASE WHEN g.home_team_id=t.team_id THEN g.away_goals ELSE g.home_goals END) ga
    FROM teams t JOIN games g ON t.team_id IN (g.home_team_id, g.away_team_id) AND g.played=1
    GROUP BY t.team_id""").fetchall()
for r in sorted(rows, key=lambda r: -(r["w"] * 2 + r["otl"])):
    l = r["gp"] - r["w"] - r["otl"]
    print(f"{r['name']:<18}{r['gp']:>4}{r['w']:>4}{l:>4}{r['otl']:>5}{r['w'] * 2 + r['otl']:>5}{r['gf']:>5}{r['ga']:>5}")

tot = conn.execute("SELECT COUNT(*) n, AVG(home_goals+away_goals) gpg FROM games WHERE played=1").fetchone()
ev = conn.execute("SELECT COUNT(*) FROM game_events").fetchone()[0]
shots = conn.execute("SELECT COUNT(*) FROM game_events WHERE event_type='shot'").fetchone()[0]
print(f"\n{tot['n']} games, {tot['gpg']:.2f} goals/game, {shots / tot['n']:.1f} shots/game (both teams), "
      f"{ev} stored events.")

# Replay check: re-simulating a game with its stored seed must reproduce the score.
g = conn.execute("SELECT * FROM games WHERE played=1 ORDER BY game_id LIMIT 1").fetchone()
conn.execute("DELETE FROM game_events WHERE game_id=?", (g["game_id"],))
conn.execute("DELETE FROM player_game_stats WHERE game_id=?", (g["game_id"],))
hg, ag = sim.simulate_game(conn, g["game_id"])
print(f"Replay game {g['game_id']}: stored {g['home_goals']}-{g['away_goals']}, replayed {hg}-{ag} "
      f"-> {'OK' if (hg, ag) == (g['home_goals'], g['away_goals']) else 'MISMATCH'}")
conn.commit()
