"""
KaggleLoader reads the pre-scraped game-metadata dataset you
download from Kaggle (name, release date, genres, review counts —
e.g. the fronkongames/artermiloff Steam Games Dataset). It knows
nothing about SQLite — DatabaseWriter takes what this class
produces and writes it.

NOTE: column names below are placeholders. Once you've picked
a specific Kaggle dataset, you'll need to adjust the column
names to match its actual CSV headers — Kaggle dataset schemas
vary and this is the one part of the pipeline you can't fully
write until you've downloaded the real file and looked at it.

Historical monthly player counts are NOT sourced from here
anymore — see steamcharts_scraper.py. This class's job now
includes defining the cohort itself: select_cohort() below
turns your research criteria (release window, review threshold)
into a concrete, reproducible list of appids.
"""
import pandas as pd


class KaggleLoader:
    def __init__(self, csv_path: str):
        self.df = pd.read_csv(csv_path)

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
        release_dates = pd.to_datetime(self.df["release_date"], errors="coerce")
        mask = (
            (release_dates >= release_start)
            & (release_dates <= release_end)
            & (self.df["total_reviews"] >= min_reviews)
        )
        qualifying = self.df[mask].copy()

        if sample_size is not None and len(qualifying) > sample_size:
            qualifying = qualifying.sample(n=sample_size, random_state=random_state)

        return qualifying.reset_index(drop=True)

    def iter_games(self):
        """
        Yields one dict per unique game, matching the fields
        DatabaseWriter.insert_game expects. Deduplicates in case
        the source CSV has one row per game-month rather than
        one row per game.
        """
        game_cols = [
            "appid", "name", "release_date", "developer",
            "publisher", "price_usd_launch", "total_reviews",
            "review_score_percent",
        ]
        unique_games = self.df.drop_duplicates(subset="appid")
        for _, row in unique_games.iterrows():
            yield {col: row.get(col) for col in game_cols}

    def iter_genres(self):
        """
        Yields (appid, genre_name) pairs. Assumes the source data
        has a 'genres' column as a comma-separated string per game —
        adjust the split logic once you see the real column format.
        """
        for _, row in self.df.drop_duplicates(subset="appid").iterrows():
            genres_raw = row.get("genres")
            if pd.isna(genres_raw):
                continue
            for genre_name in str(genres_raw).split(","):
                yield row["appid"], genre_name.strip()

    # NOTE: iter_monthly_metrics() was removed — historical monthly
    # player counts are now sourced from SteamChartsScraper instead
    # of a pre-packaged dataset, to avoid the survivorship bias of
    # datasets limited to "current top 100" games. See
    # steamcharts_scraper.py.
