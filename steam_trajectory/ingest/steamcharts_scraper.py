"""
SteamChartsScraper fetches monthly historical player-count data
directly from individual SteamCharts pages (steamcharts.com/app/<appid>),
for a specific list of appids you've already chosen (see
KaggleLoader.select_cohort). It knows nothing about SQLite —
DatabaseWriter takes what this class produces and writes it.

Why scrape instead of using a pre-packaged dataset: the easiest
pre-scraped historical dataset available only covers the "current
top 100" games, which is a survivorship-biased sample (it's
dominated by long-lived evergreen titles). Scraping SteamCharts
directly for your own deliberately-chosen cohort avoids that bias
entirely, at the cost of doing the scraping yourself.

Politeness practices built in (see conversation notes / README
for the reasoning):
  - a real, identifying User-Agent header
  - a fixed delay between requests (never parallelized)
  - local HTML caching, so re-running the script never re-fetches
    a page you already have
  - checked against steamcharts.com/robots.txt, which currently
    has no disallow rules for this kind of access

NOTE: the HTML parsing below assumes SteamCharts' current table
structure (a single <table> with Month / Avg. Players / Gain /
% Gain / Peak Players columns). Sites restructure their HTML
without warning — inspect a real page's source (right-click ->
Inspect) before your first full run, and adjust the BeautifulSoup
selectors if the structure has changed.
"""
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


class SteamChartsScraper:
    BASE_URL = "https://steamcharts.com/app/{appid}"
    USER_AGENT = "steam-trajectory-research-project (personal portfolio project)"

    def __init__(self, cache_dir: str = "data/raw_html/steamcharts",
                 request_delay_seconds: float = 2.0):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.request_delay_seconds = request_delay_seconds

    def _fetch_html(self, appid: int) -> str:
        """
        Returns the page HTML for a given appid, using a cached
        local copy if one already exists — this is what makes
        re-running the script safe and fast after a partial run
        or a crash.
        """
        cache_path = self.cache_dir / f"{appid}.html"
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")

        response = requests.get(
            self.BASE_URL.format(appid=appid),
            headers={"User-Agent": self.USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
        cache_path.write_text(response.text, encoding="utf-8")

        # Delay happens only on an actual network request — cached
        # pages return instantly, so a rerun over an already-scraped
        # cohort doesn't need to wait at all.
        time.sleep(self.request_delay_seconds)
        return response.text

    def get_monthly_history(self, appid: int) -> list[dict]:
        """
        Parses a game's SteamCharts page into a list of dicts,
        one per month, matching the fields
        DatabaseWriter.insert_monthly_metric expects
        (avg_players, peak_players; est_owners_low/high are left
        None since SteamCharts doesn't report ownership estimates —
        those still come from the Kaggle metadata dataset).
        """
        html = self._fetch_html(appid)
        soup = BeautifulSoup(html, "html.parser")

        table = soup.find("table", class_="common-table")
        if table is None:
            # Page structure didn't match what we expected — surface
            # this loudly rather than silently returning nothing,
            # since it usually means the site changed or the appid
            # has no SteamCharts page at all.
            raise ValueError(
                f"Could not find expected table on SteamCharts page for "
                f"appid {appid}. Site structure may have changed — "
                f"inspect the page manually."
            )

        records = []
        rows = table.find("tbody").find_all("tr")
        for row in rows:
            cells = [cell.get_text(strip=True) for cell in row.find_all("td")]
            if len(cells) < 5:
                continue
            month_str, avg_players_str, _gain, _pct_gain, peak_players_str = cells[:5]
            records.append({
                "appid": appid,
                "month": month_str,
                "avg_players": _to_int(avg_players_str),
                "peak_players": _to_int(peak_players_str),
                "est_owners_low": None,
                "est_owners_high": None,
                "source": "steamcharts",
            })
        return records


def _to_int(value: str) -> int | None:
    """SteamCharts formats numbers with commas (e.g. '12,345') — this
    strips that and handles blank cells gracefully."""
    cleaned = value.replace(",", "").strip()
    return int(cleaned) if cleaned.isdigit() else None
