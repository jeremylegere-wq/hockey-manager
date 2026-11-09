PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS leagues (
    league_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT,
    level INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS seasons (
    season_id INTEGER PRIMARY KEY,
    league_id INTEGER NOT NULL REFERENCES leagues(league_id),
    label TEXT NOT NULL,              -- e.g. '2026-27'
    start_date TEXT NOT NULL,
    end_date TEXT,
    UNIQUE (league_id, label)
);

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY,
    league_id INTEGER NOT NULL REFERENCES leagues(league_id),
    name TEXT NOT NULL,
    abbrev TEXT NOT NULL,
    logo_path TEXT,
    UNIQUE (league_id, abbrev)
);

CREATE TABLE IF NOT EXISTS players (
    player_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    birth_date TEXT NOT NULL,
    position TEXT NOT NULL CHECK (position IN ('C','LW','RW','D','G')),
    shoots TEXT,
    height_cm INTEGER,
    weight_kg INTEGER,
    archetype TEXT,                   -- sniper, two-way, defensive D, etc.
    team_id INTEGER REFERENCES teams(team_id),
    headshot_path TEXT,
    status TEXT NOT NULL DEFAULT 'active',  -- active, injured, retired, prospect
    source TEXT NOT NULL DEFAULT 'generated' -- generated, imported, custom
);

-- Current ratings (1-20 scale), one row per player
CREATE TABLE IF NOT EXISTS player_attributes (
    player_id INTEGER PRIMARY KEY REFERENCES players(player_id),
    shooting INTEGER, passing INTEGER, skating INTEGER, stickhandling INTEGER,
    checking INTEGER, defense INTEGER, faceoffs INTEGER, goaltending INTEGER,
    stamina INTEGER, potential INTEGER, updated_on TEXT
);

-- Historical ratings: snapshot per player per season (the thing the FHM view lacks)
CREATE TABLE IF NOT EXISTS attribute_history (
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    shooting INTEGER, passing INTEGER, skating INTEGER, stickhandling INTEGER,
    checking INTEGER, defense INTEGER, faceoffs INTEGER, goaltending INTEGER,
    stamina INTEGER, potential INTEGER,
    PRIMARY KEY (player_id, season_id)
);

CREATE TABLE IF NOT EXISTS contracts (
    contract_id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    team_id INTEGER NOT NULL REFERENCES teams(team_id),
    start_season INTEGER NOT NULL,
    years INTEGER NOT NULL,
    cap_hit INTEGER NOT NULL,
    contract_type TEXT NOT NULL DEFAULT 'standard',  -- standard, entry_level, two_way
    no_trade INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS games (
    game_id INTEGER PRIMARY KEY,
    season_id INTEGER NOT NULL REFERENCES seasons(season_id),
    game_date TEXT NOT NULL,
    home_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    away_team_id INTEGER NOT NULL REFERENCES teams(team_id),
    home_goals INTEGER, away_goals INTEGER,
    went_to_ot INTEGER DEFAULT 0,
    played INTEGER NOT NULL DEFAULT 0,
    seed INTEGER                       -- RNG seed so any game can be replayed exactly
);

-- Event-level log: shots, goals, saves, penalties. Everything else derives from this.
CREATE TABLE IF NOT EXISTS game_events (
    event_id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    seq INTEGER NOT NULL,
    period INTEGER NOT NULL,
    clock_sec INTEGER NOT NULL,        -- seconds elapsed in the period
    event_type TEXT NOT NULL,          -- shot, goal, save, penalty, hit, faceoff
    team_id INTEGER REFERENCES teams(team_id),
    player_id INTEGER REFERENCES players(player_id),
    opp_player_id INTEGER REFERENCES players(player_id),
    xg REAL,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_game ON game_events(game_id, seq);

CREATE TABLE IF NOT EXISTS player_game_stats (
    game_id INTEGER NOT NULL REFERENCES games(game_id),
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    team_id INTEGER NOT NULL REFERENCES teams(team_id),
    toi_sec INTEGER, goals INTEGER DEFAULT 0, assists INTEGER DEFAULT 0,
    shots INTEGER DEFAULT 0, saves INTEGER DEFAULT 0, shots_against INTEGER DEFAULT 0,
    PRIMARY KEY (game_id, player_id)
);

CREATE TABLE IF NOT EXISTS injuries (
    injury_id INTEGER PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(player_id),
    start_date TEXT NOT NULL,
    expected_return TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    txn_id INTEGER PRIMARY KEY,
    txn_date TEXT NOT NULL,
    txn_type TEXT NOT NULL,            -- trade, signing, waiver, release, draft, retire
    player_id INTEGER REFERENCES players(player_id),
    from_team_id INTEGER REFERENCES teams(team_id),
    to_team_id INTEGER REFERENCES teams(team_id),
    detail TEXT
);

CREATE TABLE IF NOT EXISTS game_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    current_date TEXT NOT NULL,
    current_season_id INTEGER REFERENCES seasons(season_id),
    rng_seed INTEGER NOT NULL
);
