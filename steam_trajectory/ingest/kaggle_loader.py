"""
KaggleLoader reads the fronkongames/steam-games-dataset JSON export
(games.json) downloaded from Kaggle. Switched from the CSV version
after validation revealed row-level misalignment in the CSV export
(an unescaped comma in a free-text field was corrupting column
alignment for many rows — confirmed by AppID containing a game's
NAME instead of a number, and 100% of release dates failing to
parse). JSON has no such ambiguity, since fields are explicitly
keyed rather than positional.

The raw JSON is a dict keyed by appid string, e.g.:
    {"906850": {"name": ..., "release_date": {"date": "...", ...},
                "genres": [...], "developers": [...], ...}, ...}

This class flattens that into a pandas DataFrame with the same
column names the rest of the pipeline (select_cohort, iter_games,
iter_genres) already expects, so nothing downstream needs to change.
"""
import json

import pandas as pd


class KaggleLoader:
    def __init__(self, json_path: str):
        with open(json_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        records = []
        for appid, game in raw.items():
            release_date = game.get("release_date")
            if isinstance(release_date, dict):
                release_date = release_date.get("date")

            positive = game.get("positive") or 0
            negative = game.get("negative") or 0
            total_reviews = positive + negative
            review_score_percent = (
                positive / total_reviews * 100 if total_reviews > 0 else None
            )

            genres = game.get("genres") or []
            developers = game.get("developers") or []
            publishers = game.get("publishers") or []

            records.append({
                "AppID": int(appid),
                "Name": game.get("name"),
                "Release date": release_date,
                "Developers": ", ".join(developers) if developers else None,
                "Publishers": ", ".join(publishers) if publishers else None,
                "Price": game.get("price"),
                "total_reviews": total_reviews,
                "review_score_percent": review_score_percent,
                "Genres": ", ".join(genres) if genres else None,
            })

        self.df = pd.DataFrame.from_records(records)

    def select_cohort(self, release_start: str, release_end: str,
                       min_reviews: int, sample_size: int | None = None,
                       random_state: int = 42) -> pd.DataFrame:
        """
        Filters the full metadata dataset down to games matching
        your research criteria, and returns them as a DataFrame
        (one row per qualifying game). This is what turns "2019-2022
        releases with 500+ reviews" from a design decision into an
        actual, reproducible list of appids — rerun this with
        different arguments and you get a different but still-valid
        cohort, no manual list-editing required.

        If sample_size is set and there are more qualifying games
        than that, a random sample is taken (with a fixed random_state
        so it's reproducible run to run).
        """
        release_dates = pd.to_datetime(self.df["Release date"], errors="coerce")
        mask = (
            (release_dates >= release_start)
            & (release_dates <= release_end)
            & (self.df["total_reviews"] >= min_reviews)
        )
        qualifying = self.df[mask].copy()

        if sample_size is not None and len(qualifying) > sample_size:
            qualifying = qualifying.sample(n=sample_size, random_state=random_state)

        return qualifying.reset_index(drop=True)

    @staticmethod
    def iter_games(df: pd.DataFrame):
        """
        Yields one dict per unique game, matching the fields
        DatabaseWriter.insert_game expects. Takes a DataFrame
        directly (e.g. loaded from a saved candidates CSV) — this
        is a staticmethod specifically so notebook 01 can call it
        without needing to reload the full ~126K-game JSON dataset
        just to process an already-selected cohort.
        """
        column_map = {
            "AppID": "appid",
            "Name": "name",
            "Release date": "release_date",
            "Developers": "developer",
            "Publishers": "publisher",
            "Price": "price_usd_launch",
            "total_reviews": "total_reviews",
            "review_score_percent": "review_score_percent",
        }
        unique_games = df.drop_duplicates(subset="AppID")
        for _, row in unique_games.iterrows():
            yield {schema_col: row.get(source_col)
                   for source_col, schema_col in column_map.items()}

    @staticmethod
    def iter_genres(df: pd.DataFrame):
        """
        Yields (appid, genre_name) pairs. The 'Genres' column here
        is a comma-joined string. Same staticmethod reasoning as
        iter_games above — works directly on a saved candidates
        DataFrame, no full-dataset reload required.
        """
        for _, row in df.drop_duplicates(subset="AppID").iterrows():
            genres_raw = row.get("Genres")
            if pd.isna(genres_raw):
                continue
            for genre_name in str(genres_raw).split(","):
                yield row["AppID"], genre_name.strip()

    # NOTE: iter_monthly_metrics() was removed — historical monthly
    # player counts are now sourced from SteamChartsScraper instead
    # of a pre-packaged dataset, to avoid the survivorship bias of
    # datasets limited to "current top 100" games. See
    # steamcharts_scraper.py.
