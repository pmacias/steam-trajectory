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
import hashlib
import json

import pandas as pd


def _stable_hash_score(appid: int, salt: str = "steam_trajectory_cohort") -> float:
    """
    Deterministic pseudo-random score in [0, 1), derived only from
    an appid's own hash — not its position within any DataFrame.
    Selecting the top `sample_size` games by this score is stable
    under upstream additions/removals: a game's inclusion depends
    only on its own ID, never on how many other rows happen to
    precede it or how large the overall pool is. This matters in
    practice — plain pandas .sample(random_state=...) draws based
    on total row count, so even a SORTED pool can produce an almost
    entirely different sample if the pool's size changes at all
    (e.g. a filter change excluding a different number of titles),
    which was silently invalidating most of the scraper's cache on
    every rerun.
    """
    h = hashlib.sha256(f"{salt}_{appid}".encode()).hexdigest()
    return int(h, 16) / 16 ** len(h)


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

    # Steam sells non-game software (art tools, VR utilities, RPG-making
    # tools, etc.) through the same storefront/review system, so a
    # release-date + review-count filter alone can let a few slip in.
    # Two checks combined, since each covers the other's blind spot:
    #   1. WHITELIST — game must have at least one gameplay-adjacent
    #      genre. Robust to non-game categories we haven't seen yet.
    #   2. BLACKLIST — game must NOT carry any known non-game/software
    #      category. Needed because some tools carry a genre ALSO used
    #      by real games (e.g. "Early Access" is a dev-status label, not
    #      gameplay — confirmed empirically: ScreenPlay and XSOverlay,
    #      both non-game VR/utility software, are tagged "Early Access"
    #      alongside "Utilities").
    #
    # NOTE: "Casual", "Indie", and "Free To Play" (note exact casing —
    # the dataset uses "Free To Play", not "Free to Play") were
    # initially excluded from the whitelist as ambiguous distribution/
    # status labels, but checking against real data showed this wrongly
    # dropped ~190 genuine games (e.g. inbento, Puyo Puyo Champions,
    # Shady Part of Me) whose ONLY genre tag was one of these three.
    # "Early Access" stays excluded — Easy Pose (a non-game 3D posing
    # tool, tagged only "Early Access") confirms it's still too
    # tool-ambiguous to trust on its own.
    _REAL_GAME_GENRES = {
        "Action", "Adventure", "RPG", "Racing", "Simulation",
        "Sports", "Strategy", "Massively Multiplayer",
        "Violent", "Gore", "Nudity", "Sexual Content",
        "Casual", "Indie", "Free To Play",
    }
    _NON_GAME_CATEGORIES = {
        "Design & Illustration", "Animation & Modeling", "Education",
        "Utilities", "Web Publishing", "Photo Editing",
        "Software Training", "Video Production", "Audio Production",
        "Accounting", "Game Development",
    }

    def select_cohort(self, release_start: str, release_end: str,
                       min_reviews: int, sample_size: int | None = None) -> pd.DataFrame:
        """
        Filters the full metadata dataset down to games matching
        your research criteria, and returns them as a DataFrame
        (one row per qualifying game). This is what turns "2019-2022
        releases with 500+ reviews" from a design decision into an
        actual, reproducible list of appids — rerun this with
        different arguments and you get a different but still-valid
        cohort, no manual list-editing required.

        Also excludes non-game software (art/utility/dev tools sold
        through the same Steam storefront) — see _REAL_GAME_GENRES
        and _NON_GAME_CATEGORIES above.

        If sample_size is set and there are more qualifying games
        than that, a deterministic per-game hash selects the sample
        (see _stable_hash_score) — stable across reruns even when
        this filter's other criteria change and the qualifying pool
        size shifts, unlike pandas' position-based .sample().
        """
        release_dates = pd.to_datetime(self.df["Release date"], errors="coerce")
        mask = (
            (release_dates >= release_start)
            & (release_dates <= release_end)
            & (self.df["total_reviews"] >= min_reviews)
        )
        qualifying = self.df[mask].copy()

        def is_real_game(genres_str):
            if pd.isna(genres_str):
                return False
            game_genres = {g.strip() for g in str(genres_str).split(",")}
            has_gameplay_genre = len(game_genres & self._REAL_GAME_GENRES) > 0
            has_non_game_tag = len(game_genres & self._NON_GAME_CATEGORIES) > 0
            return has_gameplay_genre and not has_non_game_tag

        qualifying = qualifying[qualifying["Genres"].apply(is_real_game)]

        if sample_size is not None and len(qualifying) > sample_size:
            qualifying = qualifying.copy()
            qualifying["_sort_key"] = qualifying["AppID"].apply(_stable_hash_score)
            qualifying = qualifying.sort_values("_sort_key").head(sample_size)
            qualifying = qualifying.drop(columns="_sort_key")

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
