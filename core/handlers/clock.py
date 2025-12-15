import re
from .handler import Handler
from datetime import datetime
from zoneinfo import ZoneInfo
from tzlocal import get_localzone
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderUnavailable, GeocoderServiceError
from timezonefinder import TimezoneFinder


TZ_TRIGGER_RE = re.compile(
    r"\b(?:in|at|for)\s+([a-zA-Z\s,_-]+)",
    re.IGNORECASE
)

class Clock(Handler):
    def __init__(self):
        super().__init__()
        self.local_tz: ZoneInfo = get_localzone()
        self.geolocator = Nominatim(user_agent="clock_handler")
        self.tz_finder = TimezoneFinder()
        self._tz_cache: dict[str, ZoneInfo] = {}

    def handle_query(self, query: str):
        tz = self._extract_tz(query)
        now = datetime.now(tz)

        if "time" in query:
            response = self._time_response(now, tz)
        elif "date" in query or "day" in query:
            response = self._date_response(now)
        else:
            return self._respond(False, "time or date not found in query")

        return self._respond(True, response)

    # -----------------------
    # Parsing + Resolution
    # -----------------------

    def _extract_tz(self, query: str) -> ZoneInfo:
        match = TZ_TRIGGER_RE.search(query)
        if not match:
            return self.local_tz

        place = match.group(1).strip(" ?.,").lower()

        # Cache hit
        if place in self._tz_cache:
            return self._tz_cache[place]

        tz = self._resolve_place_to_tz(place)
        self._tz_cache[place] = tz
        return tz

    def _resolve_place_to_tz(self, place: str) -> ZoneInfo:
        try:
            location = self.geolocator.geocode(place, language="en", timeout=5)
            if not location:
                return self.local_tz

            tzname = self.tz_finder.timezone_at(
                lat=location.latitude,
                lng=location.longitude
            )
            if not tzname:
                return self.local_tz

            return ZoneInfo(tzname)

        except (GeocoderUnavailable, GeocoderServiceError):
            # Network, SSL, captive portal, rate limit, etc.
            return self.local_tz

    # -----------------------
    # Responses
    # -----------------------

    def _time_response(self, dt: datetime, tz: ZoneInfo) -> str:
        suffix = ""
        if tz != self.local_tz:
            suffix = f" in {tz.key.split('/')[-1]}"

        return f"the time is {self.speakable_time(dt)}{suffix}"

    def _date_response(self, dt: datetime) -> str:
        year = str(dt.year)
        return f"today is {dt.strftime("%A, %B %-d,")} {year[:2]} {year[-2:]}"

    def speakable_time(self, dt: datetime) -> str:
        hour = dt.strftime("%-I")
        minute = dt.strftime("%M")
        period = dt.strftime("%p")

        if minute == "00":
            minute = ""
        elif dt.minute < 10:
            minute = minute.replace("0", "oh", 1)

        return f"{hour} {minute} {period}"
    

if __name__ == "__main__":
    c = Clock()
    print(c.local_tz)
    resp = c.handle_query("what time is it")
    print(resp)
    resp = c.handle_query("what day is it today")
    print(resp)
