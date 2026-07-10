"""
SteamAPIClient talks to the official, live Steam Web API only.
It knows nothing about SQLite or the project's schema — it just
fetches data and hands back plain Python objects (dicts/lists).
DatabaseWriter is responsible for turning those into rows.
"""
import requests
import time


class SteamAPIClient:
    REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
    CURRENT_PLAYERS_URL = (
        "https://api.steampowered.com/ISteamUserStats/"
        "GetNumberOfCurrentPlayers/v1/"
    )

    def __init__(self, request_delay_seconds: float = 1.0):
        # Being polite to a free, unauthenticated API — a fixed
        # delay between calls avoids hammering it and getting
        # rate-limited or blocked.
        self.request_delay_seconds = request_delay_seconds

    def get_reviews(self, appid: int, num_reviews: int = 100,
                     language: str = "english") -> list[dict]:
        """
        Fetch up to num_reviews reviews for a given appid.
        Returns a list of dicts matching the shape DatabaseWriter.insert_review
        expects (keys: recommendationid, review, voted_up, votes_up,
        votes_funny, timestamp_created, author -> playtime_at_review).
        """
        params = {
            "json": 1,
            "filter": "recent",
            "language": language,
            "num_per_page": min(num_reviews, 100),
        }
        response = requests.get(
            self.REVIEWS_URL.format(appid=appid), params=params, timeout=10
        )
        response.raise_for_status()
        data = response.json()
        time.sleep(self.request_delay_seconds)
        return data.get("reviews", [])

    def get_current_player_count(self, appid: int) -> int | None:
        """Fetch the live concurrent player count for a game."""
        response = requests.get(
            self.CURRENT_PLAYERS_URL, params={"appid": appid}, timeout=10
        )
        response.raise_for_status()
        data = response.json()
        time.sleep(self.request_delay_seconds)
        return data.get("response", {}).get("player_count")
