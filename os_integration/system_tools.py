import json
import datetime
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET


def get_current_datetime() -> str:
    """Returns the current local date and time as a clean string."""
    now = datetime.datetime.now()
    return now.strftime("Current time: %I:%M %p, Date: %A, %B %d, %Y")


def get_local_weather(city: str = "") -> str:
    """
    Fetches current weather using wttr.in JSON API.
    Returns clean plain-English text (no HTML, no emoji, no unicode symbols).
    """
    try:
        encoded = urllib.parse.quote(city.strip()) if city.strip() else ""
        url = f"https://wttr.in/{encoded}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        cur = data["current_condition"][0]
        temp = cur["temp_C"]
        feels = cur["FeelsLikeC"]
        desc = cur["weatherDesc"][0]["value"]
        humid = cur["humidity"]
        wind = cur["windspeedKmph"]

        areas = data.get("nearest_area", [{}])
        if areas and areas[0]:
            area = areas[0].get("areaName", [{}])[0].get("value", city or "your location")
            region = areas[0].get("region", [{}])[0].get("value", "")
        else:
            area, region = city or "your location", ""

        loc = f"{area}, {region}" if region else area
        return (
            f"{loc}: {desc}, {temp} degrees Celsius "
            f"(feels like {feels}), Humidity {humid} percent, Wind {wind} km/h"
        )
    except Exception:
        return "Weather data is currently unavailable. The system may be offline."


def get_top_news() -> str:
    """
    Fetches the top 3 headlines from BBC News RSS feed.
    Safe offline fallback included.
    """
    try:
        url = "http://feeds.bbci.co.uk/news/rss.xml"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            xml_data = r.read()

        root = ET.fromstring(xml_data)
        items = root.findall(".//item")[:3]
        headlines = []
        for i, item in enumerate(items, 1):
            title = item.find("title").text
            headlines.append(f"{i}. {title}")

        if not headlines:
            return "No news headlines found at this time."
        return "\n".join(headlines)
    except Exception:
        return "Recent news headlines are currently unavailable (system is offline)."
