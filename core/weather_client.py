import os
import requests

API_KEY = os.getenv("WEATHER_API_KEY")


def get_weather_data(zipcode):
    """
    Fetch average temperature data using WeatherAPI.com (safe version).
    - Works with free-tier forecast endpoint
    - Falls back to simulated data if API fails
    """
    if not API_KEY:
        print("⚠️ WEATHER_API_KEY not found in .env — returning mock data.")
        return _mock_data()

    try:
        url = f"http://api.weatherapi.com/v1/forecast.json?key={API_KEY}&q={zipcode}&days=3"
        response = requests.get(url, timeout=10)
        data = response.json()

        # Validate response
        if not isinstance(data, dict) or "forecast" not in data:
            print("⚠️ Invalid API response:", data)
            return _mock_data()

        forecast = data.get("forecast", {}).get("forecastday")
        if not forecast:
            print("⚠️ Missing forecast data in response.")
            return _mock_data()

        # Compute average of next 3 forecast days
        temps = [day["day"]["avgtemp_f"] for day in forecast if "day" in day]
        avg_temp = round(sum(temps) / len(temps), 2) if temps else 0

        # Spread across 12 months (for demo)
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        return {m: round(avg_temp + (i - 6) * 1.3, 1) for i, m in enumerate(months)}

    except Exception as e:
        print("⚠️ Weather API error:", e)
        return _mock_data()


def _mock_data():
    """Generate fake temperature data for fallback."""
    import random
    months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
    return {m: round(random.uniform(30, 90), 1) for m in months}
