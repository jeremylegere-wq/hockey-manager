"""SQLite schema v4 (v3 added teams.parent_team_id and players.club_id; v4 the player_ratings layer; see migrate()). Attribute columns are generated from hs.attributes so the model has one source of truth."""
from __future__ import annotations

from .attributes import ALL_ATTRS, RATING_COLS

SCHEMA_VERSION = 4


def ddl() -> str:
    attr_cols = ",\n    ".join(f"{a} INTEGER" for a in ALL_ATTRS)
    rating_cols = ",\n    ".join(f"{a} INTEGER" for a in RATING_COLS)
    return f"""
PRAGMA foreign_keys = ON;

CREATE TABLE pack_info (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE leagues (
    league_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL, abbr TEXT NOT NULL, country TEXT,
    level INTEGER, games_per_team INTEGER
);

CREATE TABLE seasons (
    season_id INTEGER PRIMARY KEY,
    league_id INTEGER NOT NULL REFERENCES leagues(league_id),
    start_year INTEGER NOT NULL, label TEXT NOT NULL, start_date TEXT, end_date TEXT,
    UNIQUE (league_id, start_year)
);

CREATE TABLE teams (
    team_id INTEGER PRIMARY KEY,
    league_id INTEGER NOT NULL REFERENCES leagues(league_id),
    name TEXT NOT NULL, nickname TEXT, abbr TEXT NOT NULL,
    conference TEXT, division TEXT, primary_color TEXT, secondary_color TEXT, logo_path TEXT,
    parent_team_id INTEGER            -- affiliation: farm/minor club -> NHL organisation
);

CREATE TABLE players (
    player_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL, last_name TEXT NOT NULL, birth_date TEXT NOT NULL,
    position TEXT NOT NULL CHECK (position IN ('C','LW','RW','D','G')),
    shoots TEXT, height_cm INTEGER, weight_kg INTEGER, nationality TEXT,
    team_id INTEGER REFERENCES teams(team_id),
    status TEXT NOT NULL DEFAULT 'active', headshot_path TEXT, jersey_number INTEGER,
    club_id INTEGER                   -- the club he plays for this season (any league); team_id = NHL organisation
);

CREATE TABLE player_attributes (
    player_id INTEGER PRIMARY KEY REFERENCES players(player_id),
    {attr_cols},
    potential INTEGER
);

CREATE TABLE attribute_history (
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    season_start_year INTEGER NOT NULL,
    {attr_cols},
    potential INTEGER,
    PRIMARY KEY (player_id, season_start_year)
);

CREATE TABLE contracts (
    contract_id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    team_id INTEGER NOT NULL REFERENCES teams(team_id),
    start_year INTEGER NOT NULL, years INTEGER NOT NULL, cap_hit INTEGER NOT NULL,
    contract_type TEXT DEFAULT 'standard', no_trade INTEGER DEFAULT 0
);

CREATE TABLE skater_season_stats (
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    season_start_year INTEGER NOT NULL, team_id INTEGER, league_id INTEGER,
    split TEXT NOT NULL CHECK (split IN ('RS','PO','PS')),
    gp INTEGER, g INTEGER, a INTEGER, pim INTEGER, plus_minus INTEGER, sog INTEGER, toi_sec INTEGER
);
CREATE INDEX ix_skater_hist ON skater_season_stats(player_id, season_start_year);

CREATE TABLE goalie_season_stats (
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    season_start_year INTEGER NOT NULL, team_id INTEGER, league_id INTEGER,
    split TEXT NOT NULL CHECK (split IN ('RS','PO','PS')),
    gp INTEGER, gs INTEGER, toi_sec INTEGER, w INTEGER, l INTEGER, otl INTEGER,
    so INTEGER, ga INTEGER, sa INTEGER
);
CREATE INDEX ix_goalie_hist ON goalie_season_stats(player_id, season_start_year);

-- Simulation tables (populated by the engine, not by packs)
CREATE TABLE games (
    game_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    game_date TEXT NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    home_goals INTEGER, away_goals INTEGER,
    went_to_ot INTEGER DEFAULT 0,          -- 0 regulation, 1 overtime, 2 shootout
    game_type TEXT NOT NULL DEFAULT 'RS',   -- RS regular season, PO playoffs
    series_id TEXT, game_no INTEGER,
    played INTEGER NOT NULL DEFAULT 0, seed INTEGER
);
CREATE TABLE game_events (
    event_id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    seq INTEGER NOT NULL, period INTEGER NOT NULL, clock_sec INTEGER NOT NULL,
    event_type TEXT NOT NULL, team_id INTEGER, player_id INTEGER, opp_player_id INTEGER,
    xg REAL, detail TEXT
);
CREATE INDEX ix_events_game ON game_events(game_id, seq);
CREATE TABLE player_game_stats (
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    team_id INTEGER NOT NULL, toi_sec INTEGER, goals INTEGER DEFAULT 0, assists INTEGER DEFAULT 0,
    shots INTEGER DEFAULT 0, saves INTEGER DEFAULT 0, shots_against INTEGER DEFAULT 0,
    PRIMARY KEY (game_id, player_id)
);
CREATE TABLE injuries (
    injury_id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES players(player_id),
    start_date TEXT NOT NULL, expected_return TEXT NOT NULL, description TEXT
);
CREATE TABLE transactions (
    txn_id INTEGER PRIMARY KEY, txn_date TEXT NOT NULL, txn_type TEXT NOT NULL,
    player_id INTEGER, from_team_id INTEGER, to_team_id INTEGER, detail TEXT
);
CREATE TABLE draft_rights (
    player_id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, draft_year INTEGER, overall_pick INTEGER,
    expires_year INTEGER
);
CREATE TABLE player_dev (
    player_id INTEGER PRIMARY KEY, potential REAL, peak_age REAL, decline_age REAL, growth_rate REAL,
    decline_rate REAL
);
CREATE TABLE player_ratings (
    player_id INTEGER PRIMARY KEY,
    {rating_cols}
);
CREATE TABLE game_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_date TEXT NOT NULL, rng_seed INTEGER NOT NULL
);
"""


def top_league_sql(alias=""):
    """SQL condition selecting teams of the top league (level 1, or the only league)."""
    a = f"{alias}." if alias else ""
    return (f"{a}league_id IN (SELECT league_id FROM leagues WHERE COALESCE(level, 1) = "
            f"(SELECT MIN(COALESCE(level, 1)) FROM leagues))")


def migrate(conn) -> list:
    """Bring an older game database up to the current schema without touching existing data."""
    done = []
    cols = lambda t: {r[1] for r in conn.execute(f"PRAGMA table_info({t})")}
    if "parent_team_id" not in cols("teams"):
        conn.execute("ALTER TABLE teams ADD COLUMN parent_team_id INTEGER")
        done.append("teams.parent_team_id")
    if "jersey_number" not in cols("players"):          # v49: jersey numbers (hs/game/numbers.py)
        conn.execute("ALTER TABLE players ADD COLUMN jersey_number INTEGER")
        done.append("players.jersey_number")
    if "club_id" not in cols("players"):
        conn.execute("ALTER TABLE players ADD COLUMN club_id INTEGER")
        conn.execute("UPDATE players SET club_id=team_id WHERE status IN ('active','injured')")
        done.append("players.club_id")
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "draft_rights" not in have:
        conn.execute("CREATE TABLE draft_rights (player_id INTEGER PRIMARY KEY, team_id INTEGER NOT NULL, "
                     "draft_year INTEGER, overall_pick INTEGER, expires_year INTEGER)")
        done.append("draft_rights")
    if "player_ratings" not in have:                  # v38: the native ratings layer (hs/game/ratings.py)
        conn.execute(f"CREATE TABLE player_ratings (player_id INTEGER PRIMARY KEY, {', '.join(c + ' INTEGER' for c in RATING_COLS)})")
        done.append("player_ratings")
    if "player_dev" not in have:
        conn.execute("CREATE TABLE player_dev (player_id INTEGER PRIMARY KEY, potential REAL, peak_age REAL, "
                     "decline_age REAL, growth_rate REAL, decline_rate REAL)")
        done.append("player_dev")
    # v42: history imported from the database (hs/adapters/db_history.py) is marked and keeps names of clubs and
    # leagues outside the world; the replaced_* copies keep the same columns
    for t in ("skater_season_stats", "goalie_season_stats", "replaced_skater_season_stats", "replaced_goalie_season_stats"):
        if t not in have:
            continue
        for c in ("source", "club_name", "league_name"):
            if c not in cols(t):
                conn.execute(f"ALTER TABLE {t} ADD COLUMN {c} TEXT")
                done.append(f"{t}.{c}")
    return done
