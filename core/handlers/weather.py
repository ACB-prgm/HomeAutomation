from __future__ import annotations

from datetime import datetime, timedelta, date
from .handler import Handler
import requests
import re

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable


LOCATION_PATTERN = re.compile(
	r"\b(?:in|at|for)\s+([a-zA-Z][a-zA-Z\s,_-]*[a-zA-Z])\b",
	re.IGNORECASE
)

WEEKDAY_PATTERN = re.compile(
	r"\b(monday|mon|tuesday|tue|tues|wednesday|wed|thursday|thu|thur|thurs|friday|fri|saturday|sat|sunday|sun)\b",
	re.IGNORECASE
)

NEXT_N_DAYS_PATTERN = re.compile(
	r"\bnext\s+(\d+)\s+days?\b|\b(\d+)\s*-\s*day\b|\b(\d+)\s+days?\b",
	re.IGNORECASE
)

WEEK_PATTERN = re.compile(
	r"\b(this\s+week|next\s+week|week)\b",
	re.IGNORECASE
)

TODAY_PATTERN = re.compile(r"\btoday\b", re.IGNORECASE)
TOMORROW_PATTERN = re.compile(r"\btomorrow\b", re.IGNORECASE)
TONIGHT_PATTERN = re.compile(r"\btonight\b", re.IGNORECASE)


class Weather(Handler):
	"""
	NOAA NWS weather handler.
	- Initializes by detecting local (approx) location via IP geolocation + optional reverse geocode.
	- Parses query for location overrides (geopy forward geocode).
	- Parses intent for: today (default), tonight, tomorrow, weekday, next N days, week.
	"""

	def __init__(self, user_agent: str):
		super().__init__()
		self.user_agent = user_agent
		self.headers = {"User-Agent": self.user_agent}

		self.local_tz = datetime.now().astimezone().tzinfo

		# Geopy (Nominatim) for forward + reverse geocoding.
		# Note: Nominatim has usage policies; your call volume sounds fine.
		self._geolocator = Nominatim(user_agent=f"{self.user_agent} weather")

		# Default/base location (can be overridden per query).
		self.location, self.lat, self.lon = self._init_from_local_ip()

		# Cache forecast URLs per coordinate pair (NOAA requires a points lookup).
		self._forecast_url_cache: dict[tuple[float, float], str] = {}

	def handle_query(self, query: str):
		q = (query or "").strip()
		if not q:
			intent = self._parse_intent("")
			loc = self._default_location()
		else:
			loc = self._parse_location(q)
			intent = self._parse_intent(q)

		# Default behavior: today's local weather (daytime) if no explicit intent found.
		if intent is None:
			intent = self._parse_intent("today")
        
		try:
			forecast = self._get_forecast(loc["lat"], loc["lon"])
			spoken = self._format_forecast(forecast, intent, loc["name"])
			return self._respond(True, spoken, {"location": loc, "intent": intent, "forecast": forecast})
		except Exception:
			return self._respond(False, "Sorry, I couldn't get the weather right now.", {"location": loc, "intent": intent})

	# -------------------------
	# Local init (IP-based)
	# -------------------------

	def _init_from_local_ip(self):
		"""
		Best-effort local location detection.
		1) IP geolocation via ipapi.co
		2) Reverse geocode via Nominatim to get a speakable place name
		"""
		try:
			r = requests.get("https://ipapi.co/json/", timeout=5)
			r.raise_for_status()
			j = r.json()

			lat = float(j.get("latitude"))
			lon = float(j.get("longitude"))
			location = self._reverse_geocode_name(lat, lon)
			return location, lat, lon

		except Exception as e:
			print(e, '\n end Exception')
			# Keep defaults if anything fails.
			return "Echo Park", 34.0781, -1 * 118.2606

	def _reverse_geocode_name(self, lat: float, lon: float) -> str | None:
		try:
			loc = self._geolocator.reverse(f"{lat}, {lon}", zoom=10, language="en", timeout=5)
			if not loc:
				return None

			raw = loc.raw or {}
			addr = raw.get("address", {}) if isinstance(raw, dict) else {}
			city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("hamlet")
			state = addr.get("state")
			country = addr.get("country")

			parts = [p for p in [city, state, country] if p]
			return ", ".join(parts) if parts else None

		except (GeocoderTimedOut, GeocoderUnavailable):
			return None
		except Exception:
			return None

	def _default_location(self) -> dict:
		return {
			"name": self.location,
			"lat": self.lat,
			"lon": self.lon
		}

	# -------------------------
	# Location parsing
	# -------------------------

	def _parse_location(self, query: str) -> dict:
		"""
		Return: {"name": str, "lat": float, "lon": float}
		If query contains a location phrase and geopy resolves it, return those coords.
		Otherwise, return the default (self.location/self.lat/self.lon).
		"""
		base = self._default_location()

		# If we don't have a usable default coordinate yet, we still try to parse query.
		candidate = None

		m = LOCATION_PATTERN.search(query)
		if m:
			candidate = m.group(1).strip(" ?.,")
		else:
			# A slightly broader fallback: "weather Paris" / "forecast Cabo"
			m2 = re.search(r"\b(?:weather|forecast)\b\s+(?:in\s+|at\s+|for\s+)?([a-zA-Z][a-zA-Z\s,_-]*[a-zA-Z])\b", query, re.IGNORECASE)
			if m2:
				candidate = m2.group(1).strip(" ?.,")

		if not candidate:
			return base

		try:
			g = self._geolocator.geocode(candidate, language="en", timeout=5)
			if not g:
				return base

			name = g.address or candidate
			return {
				"name": name,
				"lat": float(g.latitude),
				"lon": float(g.longitude)
			}

		except (GeocoderTimedOut, GeocoderUnavailable):
			return base
		except Exception:
			return base

	# -------------------------
	# Intent parsing
	# -------------------------

	def _parse_intent(self, query: str) -> dict | None:
		"""
		Intent schema:
			{"mode": "single", "target_date": date, "prefer_daytime": bool, "label": str}
			{"mode": "range", "start_date": date, "days": int, "prefer_daytime": bool, "label": str}
		Default (if nothing matches): today, daytime preferred.
		"""
		now = datetime.now().astimezone(self.local_tz)
		today = now.date()

		q = (query or "").lower()

		# Tonight (single period, not necessarily daytime)
		if TONIGHT_PATTERN.search(q):
			return {
				"mode": "single",
				"target_date": today,
				"prefer_daytime": False,
				"label": "tonight"
			}

		# Tomorrow
		if TOMORROW_PATTERN.search(q):
			return {
				"mode": "single",
				"target_date": today + timedelta(days=1),
				"prefer_daytime": True,
				"label": "tomorrow"
			}

		# Explicit today
		if TODAY_PATTERN.search(q):
			return {
				"mode": "single",
				"target_date": today,
				"prefer_daytime": True,
				"label": "today"
			}

		# Next N days / N-day forecast
		m = NEXT_N_DAYS_PATTERN.search(q)
		if m:
			n = next((g for g in m.groups() if g), None)
			try:
				days = int(n) if n else 1
				days = max(1, min(days, 14))  # NOAA forecast endpoint is typically ~7 days, but keep sane.
			except Exception:
				days = 3

			return {
				"mode": "range",
				"start_date": today,
				"days": days,
				"prefer_daytime": True,
				"label": f"next {days} days"
			}

		# Week / next week
		if WEEK_PATTERN.search(q):
			return {
				"mode": "range",
				"start_date": today,
				"days": 7,
				"prefer_daytime": True,
				"label": "week"
			}

		# Specific weekday (Mon/Fri/etc)
		wm = WEEKDAY_PATTERN.search(q)
		if wm:
			target = self._weekday_to_index(wm.group(1))
			if target is not None:
				delta = (target - today.weekday()) % 7
				target_date = today + timedelta(days=delta)
				return {
					"mode": "single",
					"target_date": target_date,
					"prefer_daytime": True,
					"label": "weekday"
				}

		# If query contains generic "weather"/"forecast" with no timeframe, default to today.
		if "weather" in q or "forecast" in q:
			return {
				"mode": "single",
				"target_date": today,
				"prefer_daytime": True,
				"label": "today"
			}

		# Default: today local weather
		return {
			"mode": "single",
			"target_date": today,
			"prefer_daytime": True,
			"label": "today"
		}

	def _weekday_to_index(self, token: str) -> int | None:
		t = (token or "").strip().lower()
		m = {
			"monday": 0, "mon": 0,
			"tuesday": 1, "tue": 1, "tues": 1,
			"wednesday": 2, "wed": 2,
			"thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
			"friday": 4, "fri": 4,
			"saturday": 5, "sat": 5,
			"sunday": 6, "sun": 6
		}
		return m.get(t)

	# -------------------------
	# NOAA calls
	# -------------------------

	def _get_forecast(self, lat: float, lon: float) -> dict:
		if lat is None or lon is None:
			raise ValueError("Missing latitude/longitude for NOAA forecast request")

		key = (round(float(lat), 4), round(float(lon), 4))

		if key not in self._forecast_url_cache:
			point_resp = requests.get(
				f"https://api.weather.gov/points/{lat},{lon}",
				headers=self.headers,
				timeout=5
			)
			point_resp.raise_for_status()
			self._forecast_url_cache[key] = point_resp.json()["properties"]["forecast"]

		forecast_resp = requests.get(
			self._forecast_url_cache[key],
			headers=self.headers,
			timeout=5
		)
		forecast_resp.raise_for_status()

		return forecast_resp.json()

	# -------------------------
	# Speech formatting
	# -------------------------

	def _format_forecast(self, forecast_json: dict, intent: dict, location_name: str) -> str:
		periods = forecast_json["properties"]["periods"]
		selected = self._select_periods(periods, intent)

		loc_prefix = f"In {location_name}, " if location_name and location_name != "your area" else ""

		if not selected:
			return f"{loc_prefix}I couldn't find a matching forecast period."

		# Single period
		if intent["mode"] == "single":
			p = selected[0]
			return self._speak_period(p, loc_prefix)

		# Range summary
		lines = []
		for p in selected:
			name = p.get("name", "That day")
			short = (p.get("shortForecast") or "").lower()
			temp = p.get("temperature")
			unit = (p.get("temperatureUnit") or "").lower()

			if temp is not None and unit:
				lines.append(f"{name}: {short}, {temp} degrees {unit}")
			else:
				lines.append(f"{name}: {short}")

		# Keep it speakable: one sentence, light punctuation.
		return f"{loc_prefix}Here's the forecast for the {intent.get('label', 'next days')}. " + " ".join(lines) + "."

	def _speak_period(self, period: dict, loc_prefix: str) -> str:
		name = period.get("name", "Today")
		short = (period.get("shortForecast") or "").lower()
		temp = period.get("temperature")
		unit = (period.get("temperatureUnit") or "").lower()

		# Optional precip if present on this endpoint (not always guaranteed)
		pop = None
		try:
			pop_obj = period.get("probabilityOfPrecipitation")
			if isinstance(pop_obj, dict):
				pop = pop_obj.get("value")
		except Exception:
			pop = None

		parts = [f"{name}."]
		if short:
			parts.append(f"It will be {short}.")
		if temp is not None and unit:
			parts.append(f"The temperature will be around {temp} degrees {unit}.")
		if isinstance(pop, (int, float)) and pop >= 20:
			parts.append(f"Chance of precipitation is {int(pop)} percent.")

		return loc_prefix + " ".join(parts)

	def _select_periods(self, periods: list[dict], intent: dict) -> list[dict]:
		"""
		Select forecast periods from NOAA /forecast endpoint.
		- For single: pick the best matching period for target_date, preferring daytime if requested.
		- For range: pick one daytime period per day starting from start_date, for N days.
		"""
		now = datetime.now().astimezone(self.local_tz)
		today = now.date()

		# Build mapping of date -> daytime period (first encountered)
		daytime_by_date: dict[date, dict] = {}
		any_by_date: dict[date, dict] = {}

		for p in periods:
			start = self._parse_noaa_time(p.get("startTime"))
			if not start:
				continue

			d = start.astimezone(self.local_tz).date()
			if d not in any_by_date:
				any_by_date[d] = p

			if p.get("isDaytime") and d not in daytime_by_date:
				daytime_by_date[d] = p

		if intent["mode"] == "single":
			target: date = intent["target_date"]
			prefer_daytime = bool(intent.get("prefer_daytime", True))

			if intent.get("label") == "tonight":
				# "Tonight" is often periods[0] when evening; otherwise first non-daytime in today's date.
				for p in periods:
					if p.get("name", "").lower() == "tonight":
						return [p]
				# fallback: first non-daytime today
				for p in periods:
					start = self._parse_noaa_time(p.get("startTime"))
					if not start:
						continue
					if start.astimezone(self.local_tz).date() == today and not p.get("isDaytime"):
						return [p]
				return [periods[0]] if periods else []

			if prefer_daytime and target in daytime_by_date:
				return [daytime_by_date[target]]
			if target in any_by_date:
				return [any_by_date[target]]

			# fallback: first period
			return [periods[0]] if periods else []

		# Range mode
		start_date: date = intent["start_date"]
		days: int = int(intent["days"])
		prefer_daytime = bool(intent.get("prefer_daytime", True))

		out = []
		for i in range(days):
			d = start_date + timedelta(days=i)
			if prefer_daytime and d in daytime_by_date:
				out.append(daytime_by_date[d])
			elif d in any_by_date:
				out.append(any_by_date[d])

		# If range starts today and it's already late, daytime might be missing; allow tomorrow forward.
		if not out and days > 0:
			for i in range(1, days + 1):
				d = start_date + timedelta(days=i)
				if prefer_daytime and d in daytime_by_date:
					out.append(daytime_by_date[d])
				elif d in any_by_date:
					out.append(any_by_date[d])
				if len(out) >= days:
					break

		return out

	def _parse_noaa_time(self, iso_str: str) -> datetime | None:
		if not iso_str:
			return None
		try:
			# NOAA uses ISO8601 with timezone offset; fromisoformat handles it.
			return datetime.fromisoformat(iso_str)
		except Exception:
			return None
