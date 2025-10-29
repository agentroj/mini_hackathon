import os
import requests
import calendar
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

API_KEY = os.getenv("WEATHER_API_KEY")

MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']

# simple in-process caches
# per-month: (zipcode, year, month) -> avg temp or None
_CACHE = {}
# per-year: (zipcode, year) -> { 'Jan': val, ... }
_YEAR_CACHE = {}


def _get_json_with_backoff(url: str, timeout: int = 15, retries: int = 3):
    """HTTP GET with exponential backoff and jitter. Returns parsed JSON or raises last error."""
    delay = 0.5
    last_exc = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last_exc = e
            if attempt == retries - 1:
                break
            sleep_for = delay * (2 ** attempt) + random.uniform(0, 0.2)
            time.sleep(sleep_for)
    raise last_exc if last_exc else RuntimeError("Unknown HTTP error")


def _zeros():
    """Return a mapping of all months to 0."""
    return {m: 0 for m in MONTHS}


def _monthly_avg_temp_f(zipcode: str, year: int, month: int):
    """Fetch average temperature (°F) for a month using WeatherAPI history.
    Returns a float or None if not available.
    """
    key = (str(zipcode), int(year), int(month))
    if key in _CACHE:
        return _CACHE[key]

    try:
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1).strftime("%Y-%m-%d")
        end = date(year, month, last_day).strftime("%Y-%m-%d")
        url = (
            f"http://api.weatherapi.com/v1/history.json?key={API_KEY}"
            f"&q={zipcode}&dt={start}&end_dt={end}"
        )
        data = _get_json_with_backoff(url, timeout=15)

        forecast_days = data.get("forecast", {}).get("forecastday", []) if isinstance(data, dict) else []
        temps = []
        for d in forecast_days:
            day = d.get("day", {}) if isinstance(d, dict) else {}
            t = day.get("avgtemp_f")
            if isinstance(t, (int, float)):
                temps.append(float(t))
        value = round(sum(temps) / len(temps), 2) if temps else None
        _CACHE[key] = value
        return value
    except Exception:
        _CACHE[key] = None
        return None


def get_weather_data(zipcode, year=None, month=None):
    """
    Return a mapping of months -> average temperature (°F).
    - If year/month provided: compute that month's average via WeatherAPI history.
    - If month is None: compute all months for the given year.
    - If API key missing or data unavailable: return zeros for all months.
    """
    if not API_KEY:
        print("WEATHER_API_KEY not found in environment. Returning zeros.")
        return _zeros()

    today = date.today()
    year = int(year) if year else today.year
    month = int(month) if month else None

    result = _zeros()
    if month is None:
        # Check per-year cache first
        year_key = (str(zipcode), year)
        if year_key in _YEAR_CACHE:
            cached = _YEAR_CACHE[year_key]
            # ensure we return a copy to avoid external mutation
            return {m: cached.get(m, 0) for m in MONTHS}

        # Compute for all months in parallel with a small worker pool
        month_results = {}
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_map = {
                executor.submit(_monthly_avg_temp_f, str(zipcode), year, m): m
                for m in range(1, 13)
            }
            for fut in as_completed(future_map):
                m = future_map[fut]
                try:
                    avg = fut.result()
                except Exception:
                    avg = None
                if avg is not None:
                    month_results[m] = avg

        for m in range(1, 13):
            if m in month_results:
                result[MONTHS[m - 1]] = month_results[m]

        # populate per-year cache
        _YEAR_CACHE[year_key] = {k: result[k] for k in MONTHS}
        return result
    else:
        # Compute only the requested month
        avg = _monthly_avg_temp_f(str(zipcode), year, int(month))
        if avg is not None:
            result[MONTHS[int(month) - 1]] = avg
        return result
