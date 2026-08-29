"""Weather via Open-Meteo (free, no API key)."""

import logging

import httpx

log = logging.getLogger("deskd.weather")

_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1"
_FORECAST = ("https://api.open-meteo.com/v1/forecast"
             "?latitude={lat}&longitude={lon}&current=temperature_2m,"
             "apparent_temperature,precipitation,weather_code&daily=temperature_2m_max,"
             "temperature_2m_min,precipitation_probability_max&timezone=auto&forecast_days=1")

_CODES = {
    0: "clear sky", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
    45: "foggy", 48: "foggy", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 71: "light snow", 73: "snow",
    75: "heavy snow", 80: "rain showers", 81: "rain showers", 82: "violent showers",
    95: "thunderstorm", 96: "thunderstorm with hail",
}


async def _geocode(name: str):
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(_GEOCODE.format(q=name))
        r.raise_for_status()
        results = r.json().get("results") or []
        if not results:
            return None
        g = results[0]
        return g["latitude"], g["longitude"], g.get("name", name)


async def weather_report(location: str = "", lat: float = 0.0, lon: float = 0.0) -> str | None:
    try:
        if not (lat and lon):
            if not location:
                return None
            geo = await _geocode(location)
            if not geo:
                return f"I couldn't find the location {location}."
            lat, lon, place = geo
        else:
            place = location or "your area"
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(_FORECAST.format(lat=lat, lon=lon))
            r.raise_for_status()
            d = r.json()
        cur = d["current"]
        daily = d["daily"]
        desc = _CODES.get(cur["weather_code"], "mixed weather")
        temp = round(cur["temperature_2m"])
        feels = round(cur["apparent_temperature"])
        hi = round(daily["temperature_2m_max"][0])
        lo = round(daily["temperature_2m_min"][0])
        rain = daily.get("precipitation_probability_max", [None])[0]
        parts = [f"In {place} it's {temp} degrees with {desc}, feels like {feels}.",
                 f"Today's high is {hi}, low {lo}."]
        if isinstance(rain, (int, float)) and rain >= 30:
            parts.append(f"Carry an umbrella, {rain} percent chance of rain.")
        return " ".join(parts)
    except Exception:
        log.exception("weather failed")
        return None
