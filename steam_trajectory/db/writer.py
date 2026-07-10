"""
DatabaseWriter is the single point of contact with SQLite.
Nothing else in the pipeline should run raw SQL directly —
SteamAPIClient and KaggleLoader hand this class clean data,
and it's responsible for getting that data into the schema
correctly (including all the join-table bookkeeping).

Known limitation (a deliberate scope choice, not an oversight):
insert_* methods use INSERT OR IGNORE for reference data, so
re-running ingestion won't crash on duplicates — but it also
won't update a row that's already there. Fine for a one-time
ingestion; would need real upsert logic (INSERT ... ON CONFLICT
DO UPDATE) if you later want to refresh existing games.
"""
import sqlite3


class DatabaseWriter:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert_game(self, appid: int, name: str, release_date: str | None,
                     developer: str | None, publisher: str | None,
                     price_usd_launch: float | None, total_reviews: int | None,
                     review_score_percent: float | None) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO games
                (appid, name, release_date, developer, publisher,
                 price_usd_launch, total_reviews, review_score_percent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (appid, name, release_date, developer, publisher,
             price_usd_launch, total_reviews, review_score_percent),
        )

    def get_or_create_genre(self, genre_name: str) -> int:
        """
        Returns the genre_id for a genre name, creating it first
        if it doesn't exist yet. This is the pattern you need
        whenever a lookup table's rows get discovered incrementally
        rather than all being known up front.
        """
        self.conn.execute(
            "INSERT OR IGNORE INTO genres (name) VALUES (?)", (genre_name,)
        )
        cursor = self.conn.execute(
            "SELECT genre_id FROM genres WHERE name = ?", (genre_name,)
        )
        return cursor.fetchone()[0]

    def link_game_genre(self, appid: int, genre_name: str) -> None:
        genre_id = self.get_or_create_genre(genre_name)
        self.conn.execute(
            "INSERT OR IGNORE INTO game_genres (appid, genre_id) VALUES (?, ?)",
            (appid, genre_id),
        )

    def insert_monthly_metric(self, appid: int, month: str,
                               avg_players: int | None, peak_players: int | None,
                               est_owners_low: int | None, est_owners_high: int | None,
                               source: str) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO monthly_metrics
                (appid, month, avg_players, peak_players,
                 est_owners_low, est_owners_high, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (appid, month, avg_players, peak_players,
             est_owners_low, est_owners_high, source),
        )

    def insert_review(self, review_id: int, appid: int, review_text: str | None,
                       voted_up: bool, votes_up: int, votes_funny: int,
                       timestamp_created: int, playtime_at_review: int | None,
                       language: str) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO reviews
                (review_id, appid, review_text, voted_up, votes_up,
                 votes_funny, timestamp_created, playtime_at_review, language)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (review_id, appid, review_text, int(voted_up), votes_up,
             votes_funny, timestamp_created, playtime_at_review, language),
        )

    def get_or_create_sale_event(self, sale_name: str, start_date: str, end_date: str) -> int:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO sale_events (sale_name, start_date, end_date)
            VALUES (?, ?, ?)
            """,
            (sale_name, start_date, end_date),
        )
        cursor = self.conn.execute(
            "SELECT sale_id FROM sale_events WHERE sale_name = ?", (sale_name,)
        )
        return cursor.fetchone()[0]

    def link_game_sale_discount(self, appid: int, sale_name: str,
                                 start_date: str, end_date: str,
                                 discount_percent: float) -> None:
        sale_id = self.get_or_create_sale_event(sale_name, start_date, end_date)
        self.conn.execute(
            """
            INSERT OR IGNORE INTO game_sale_discounts (appid, sale_id, discount_percent)
            VALUES (?, ?, ?)
            """,
            (appid, sale_id, discount_percent),
        )

    def commit(self) -> None:
        self.conn.commit()
