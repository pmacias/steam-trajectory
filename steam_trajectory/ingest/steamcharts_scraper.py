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
from datetime import datetime
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

            # "Last 30 Days" is a rolling window, not a real calendar
            # month — it overlaps with whatever the current partial
            # month already is, so it's excluded to avoid a phantom
            # duplicate/overlapping data point in the time series.
            if month_str == "Last 30 Days":
                continue

            month_iso = _parse_month_to_iso(month_str)
            if month_iso is None:
                # Couldn't parse this row's month label at all —
                # skip it rather than silently storing a bad value
                # that would break sorting again.
                continue

            records.append({
                "appid": appid,
                "month": month_iso,
                "avg_players": _to_float(avg_players_str),
                "peak_players": _to_int(peak_players_str),
                "est_owners_low": None,
                "est_owners_high": None,
                "source": "steamcharts",
            })
        return records

    def get_monthly_history_batch(self, appids: list[int]) -> tuple[list[dict], list[dict]]:
        """
        Runs get_monthly_history across a list of appids, catching
        failures per-game instead of letting one bad appid crash the
        entire batch. Some games legitimately fail — no SteamCharts
        page at all, a delisted title, a transient server error —
        and that's expected at this scale, not a bug to chase down
        for every single occurrence.

        Returns (records, failures):
          - records: flat list of monthly-metric dicts for every
            game that succeeded, ready to hand to DatabaseWriter
          - failures: list of {"appid": ..., "error": ...} dicts,
            so you can see what failed and why, and decide whether
            to retry, drop, or investigate specific ones afterward
        """
        records = []
        failures = []
        for i, appid in enumerate(appids):
            try:
                records.extend(self.get_monthly_history(appid))
            except (requests.exceptions.RequestException, ValueError) as e:
                failures.append({"appid": appid, "error": str(e)})

            if (i + 1) % 20 == 0:
                print(f"Processed {i + 1}/{len(appids)} games "
                      f"({len(failures)} failures so far)...")

        return records, failures


def _parse_month_to_iso(month_str: str) -> str | None:
    """
    Converts SteamCharts' text month label (e.g. 'April 2022') into
    an ISO 8601 date string ('2022-04-01', always the first of the
    month). This matters beyond just tidiness: storing dates as
    ISO strings means plain alphabetical string sorting (MIN, MAX,
    ORDER BY) produces correct CHRONOLOGICAL order for free — no
    date-parsing needed at query time. Storing the raw text label
    instead ('April 2022', 'March 2021', ...) sorts alphabetically
    by month NAME instead, which silently produces wrong results
    (e.g. MIN() returning an April row regardless of actual
    chronological order, since 'April' sorts first alphabetically
    among month names).
    """
    try:
        parsed = datetime.strptime(month_str, "%B %Y")
        return parsed.strftime("%Y-%m-01")
    except ValueError:
        return None


def _to_int(value: str) -> int | None:
    """SteamCharts formats whole numbers (like Peak Players) with
    commas (e.g. '12,345') — this strips that and handles blank
    cells gracefully."""
    cleaned = value.replace(",", "").strip()
    return int(cleaned) if cleaned.isdigit() else None


def _to_float(value: str) -> float | None:
    """Avg. Players is reported as a decimal (e.g. '18.96'), unlike
    Peak Players which is always whole — needs its own parser since
    a decimal point makes str.isdigit() return False."""
    cleaned = value.replace(",", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None
