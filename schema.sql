-- ============================================================
-- Steam Trajectory Project — Database Schema
-- SQLite. Run this once against a fresh .db file to create
-- the full structure before any data ingestion happens.
--
-- Design notes:
--   - appid is Steam's own game ID, used as the natural primary
--     key throughout rather than inventing a surrogate one.
--   - Genres are normalized via a junction table (game_genres)
--     since a game can have multiple genres and a genre applies
--     to many games — a true many-to-many relationship.
--   - Sale discounts are normalized the same way (game_sale_discounts)
--     since discount % is a property of a (game, sale) pair, not
--     of the sale alone.
--   - FOREIGN KEY constraints enforce that you can't insert data
--     for a game/genre/sale that doesn't exist yet.
--   - UNIQUE constraints prevent duplicate rows if an ingestion
--     script gets re-run accidentally.
-- ============================================================

-- SQLite doesn't enforce foreign keys by default; this turns it on
-- for the current connection. Your ingestion code should run this
-- pragma every time it opens a connection.
PRAGMA foreign_keys = ON;

-- ------------------------------------------------------------
-- games: one row per title
-- ------------------------------------------------------------
CREATE TABLE games (
    appid               INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    release_date        DATE,
    developer           TEXT,
    publisher           TEXT,
    price_usd_launch    REAL,
    total_reviews       INTEGER,
    review_score_percent REAL
);

-- ------------------------------------------------------------
-- genres: lookup table of distinct genre names
-- ------------------------------------------------------------
CREATE TABLE genres (
    genre_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE
);

-- ------------------------------------------------------------
-- game_genres: junction table (many-to-many, games <-> genres)
-- ------------------------------------------------------------
CREATE TABLE game_genres (
    appid       INTEGER NOT NULL,
    genre_id    INTEGER NOT NULL,
    PRIMARY KEY (appid, genre_id),
    FOREIGN KEY (appid) REFERENCES games(appid),
    FOREIGN KEY (genre_id) REFERENCES genres(genre_id)
);

-- ------------------------------------------------------------
-- monthly_metrics: engagement time series, one row per
-- game per month
-- ------------------------------------------------------------
CREATE TABLE monthly_metrics (
    appid           INTEGER NOT NULL,
    month           DATE NOT NULL,      -- store as first-of-month, e.g. '2021-03-01'
    avg_players     INTEGER,
    peak_players    INTEGER,
    est_owners_low  INTEGER,
    est_owners_high INTEGER,
    source          TEXT,               -- 'steamcharts' or 'steamspy' — track provenance
    FOREIGN KEY (appid) REFERENCES games(appid),
    UNIQUE (appid, month)
);

-- ------------------------------------------------------------
-- reviews: individual review text + metadata
-- ------------------------------------------------------------
CREATE TABLE reviews (
    review_id           INTEGER PRIMARY KEY,  -- Steam's own recommendationid
    appid               INTEGER NOT NULL,
    review_text         TEXT,
    voted_up            INTEGER,   -- 0/1 boolean (SQLite has no native bool)
    votes_up            INTEGER,
    votes_funny         INTEGER,
    timestamp_created   INTEGER,   -- unix timestamp, as Steam's API returns it
    playtime_at_review  INTEGER,   -- minutes
    language            TEXT,
    FOREIGN KEY (appid) REFERENCES games(appid)
);

-- ------------------------------------------------------------
-- sale_events: one row per Steam sale period
-- ------------------------------------------------------------
CREATE TABLE sale_events (
    sale_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_name   TEXT NOT NULL,
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL
);

-- ------------------------------------------------------------
-- game_sale_discounts: junction table (many-to-many,
-- games <-> sale_events, with a discount_percent attribute)
-- ------------------------------------------------------------
CREATE TABLE game_sale_discounts (
    appid               INTEGER NOT NULL,
    sale_id             INTEGER NOT NULL,
    discount_percent    REAL,
    PRIMARY KEY (appid, sale_id),
    FOREIGN KEY (appid) REFERENCES games(appid),
    FOREIGN KEY (sale_id) REFERENCES sale_events(sale_id)
);

-- ------------------------------------------------------------
-- Indices to speed up the joins you'll be running constantly
-- during modeling (SQLite auto-indexes PRIMARY KEY and UNIQUE
-- columns, so these cover the remaining common lookup patterns)
-- ------------------------------------------------------------
CREATE INDEX idx_monthly_metrics_appid ON monthly_metrics(appid);
CREATE INDEX idx_reviews_appid ON reviews(appid);
CREATE INDEX idx_game_genres_genre_id ON game_genres(genre_id);
CREATE INDEX idx_game_sale_discounts_sale_id ON game_sale_discounts(sale_id);
