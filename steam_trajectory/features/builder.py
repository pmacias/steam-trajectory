"""
FeatureBuilder constructs the feature matrix (X) and target (y) for
the "predict later engagement from early signal" task.

CRITICAL — leakage avoidance: two fields that exist elsewhere in this
project are deliberately NOT used as features here:

  - Peak CCU (from Kaggle metadata): this is a summary statistic of
    the game's ENTIRE lifetime engagement — for many spiky_multipeak
    games, the peak occurs right at launch, meaning it overlaps
    directly with the "early" window. Using it as a feature would let
    the model partly see a compressed version of the answer.

  - Trajectory shape classification (growing/plateau/etc.): computed
    using each game's FULL tracked history, often years beyond the
    late-window cutoff. Using it as a feature would mean predicting
    the future using information only available once the future is
    already known.

Every feature here is restricted to what's genuinely knowable at (or
before) the end of the early window.
"""
import numpy as np
import pandas as pd


class FeatureBuilder:
    def __init__(self, conn):
        self.conn = conn

    def build(self, early_months: int = 3, late_start: int = 10,
              late_end: int = 12) -> tuple[pd.DataFrame, pd.Series]:
        """
        Returns (X, y):
          X — feature DataFrame, one row per game, index = appid
          y — target Series, log10(avg players in the late window)

        Games with a zero/negative early or late average are dropped
        (log is undefined there — see the LinAlgError we hit in
        02_data_visualization.ipynb for why this matters).
        """
        games = pd.read_sql("""
            SELECT appid, release_date, price_usd_launch,
                   review_score_percent, total_reviews
            FROM games
        """, self.conn)
        games["release_date"] = pd.to_datetime(games["release_date"])

        monthly = pd.read_sql("""
            SELECT appid, month, avg_players
            FROM monthly_metrics
            WHERE avg_players IS NOT NULL
        """, self.conn)
        monthly["month"] = pd.to_datetime(monthly["month"])
        monthly = monthly.merge(games[["appid", "release_date"]], on="appid")
        monthly["months_since_release"] = (
            (monthly["month"].dt.year - monthly["release_date"].dt.year) * 12
            + (monthly["month"].dt.month - monthly["release_date"].dt.month)
        )

        early = (monthly[monthly["months_since_release"] <= early_months]
                 .groupby("appid")["avg_players"].mean().rename("early_avg_players"))
        late = (monthly[(monthly["months_since_release"] >= late_start)
                        & (monthly["months_since_release"] <= late_end)]
                .groupby("appid")["avg_players"].mean().rename("late_avg_players"))

        genres = pd.read_sql("""
            SELECT gg.appid, gen.name AS genre
            FROM game_genres gg
            JOIN genres gen ON gg.genre_id = gen.genre_id
        """, self.conn)
        genre_dummies = pd.crosstab(genres["appid"], genres["genre"])
        genre_dummies.columns = [f"genre_{c}" for c in genre_dummies.columns]

        df = games.set_index("appid").join([early, late], how="inner")
        df = df.join(genre_dummies, how="left").fillna(0)

        # Drop rows where early/late is zero or negative — log is
        # undefined there (see notebook 02's LinAlgError)
        df = df[(df["early_avg_players"] > 0) & (df["late_avg_players"] > 0)]

        X = pd.DataFrame(index=df.index)
        X["early_avg_players_log"] = np.log10(df["early_avg_players"])
        X["price_usd_launch"] = df["price_usd_launch"].fillna(0)
        X["review_score_percent"] = df["review_score_percent"].fillna(
            df["review_score_percent"].median()
        )
        X["total_reviews_log"] = np.log10(df["total_reviews"].clip(lower=1))
        genre_cols = [c for c in df.columns if c.startswith("genre_")]
        X[genre_cols] = df[genre_cols]
        X["num_genres"] = df[genre_cols].sum(axis=1)

        y = np.log10(df["late_avg_players"])
        y.name = "late_avg_players_log"

        return X, y
