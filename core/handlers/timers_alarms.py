import threading
import heapq
import time
import uuid
import re
from datetime import datetime, timedelta
from dataclasses import dataclass
from tzlocal import get_localzone
from .handler import Handler
from .helpers import safe_word_to_num
from enum import Enum


class AlarmKind(str, Enum):
    TIMER = "timer"
    ALARM = "alarm"


class EventState(str, Enum):
    ACTIVE = "active"
    CANCELED = "canceled"
    FIRED = "fired"


@dataclass
class ScheduledEvent:
    id: str
    kind: AlarmKind
    run_at: datetime                        # timezone-aware
    created_at: datetime                    # timezone-aware
    label: str | None = None
    state: EventState = EventState.ACTIVE
    repeat_interval_s: int | None = None    # optional simple repeat (seconds)


class TimersAlarmsHandler(Handler):
    """
    Single-thread scheduler + heap-based priority queue.

    Public API (most useful):
    - set_timer(...)
    - set_alarm(...)
    - cancel(identifier)                    # identifier = event_id OR label
    - get_time_remaining(identifier)        # identifier = event_id OR label
    - list_active(kind=None)
    """

    _UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

    def __init__(
        self,
        on_fire=None
    ):
        super().__init__()
        self.tz = get_localzone()
        self.on_fire = on_fire  # callable(event_dict) or None

        self._cv = threading.Condition()
        self._heap: list[tuple[float, int, str]] = []            # (run_at_epoch, seq, event_id)
        self._events_by_id: dict[str, ScheduledEvent] = {}
        self._ids_by_label: dict[str, set[str]] = {}

        self._seq = 0
        self._running = False
        self._thread: threading.Thread | None = None

    # ----------------------------
    # Lifecycle
    # ----------------------------
    def start(self):
        with self._cv:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self):
        with self._cv:
            self._running = False
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout=2)

    # ----------------------------
    # Core scheduling ops
    # ----------------------------
    def set_timer(self, duration_s: int, label: str | None = None, repeat_interval_s: int | None = None) -> dict:
        if duration_s <= 0:
            return self._respond(False, "Timer duration must be > 0 seconds")

        now = self._now()
        run_at = now + timedelta(seconds=duration_s)
        event = ScheduledEvent(
            id=str(uuid.uuid4()),
            kind=AlarmKind.TIMER,
            run_at=run_at,
            created_at=now,
            label=self._normalize_label(label),
            repeat_interval_s=repeat_interval_s
        )
        self._add_event(event)
        return self._respond(True, "Timer set", self._event_payload(event))

    def set_alarm(self, run_at: datetime, label: str | None = None, repeat_interval_s: int | None = None) -> dict:
        # Force timezone-aware in handler timezone
        if run_at.tzinfo is None:
            run_at = run_at.replace(tzinfo=self.tz)
        else:
            run_at = run_at.astimezone(self.tz)

        now = self._now()
        if run_at <= now:
            return self._respond(False, "Alarm time must be in the future")

        event = ScheduledEvent(
            id=str(uuid.uuid4()),
            kind=AlarmKind.ALARM,
            run_at=run_at,
            created_at=now,
            label=self._normalize_label(label),
            repeat_interval_s=repeat_interval_s
        )
        self._add_event(event)
        return self._respond(True, "Alarm set", self._event_payload(event))

    def cancel(self, identifier: str) -> dict:
        events = self._resolve(identifier)
        if not events:
            return self._respond(False, f"No active timer/alarm found for '{identifier}'")

        # Cancel all matches; you can change policy to "cancel soonest only" if preferred
        canceled = []
        with self._cv:
            for ev in events:
                if ev.state != EventState.ACTIVE:
                    continue
                ev.state = EventState.CANCELED
                self._unindex_label(ev)
                canceled.append(ev)
            self._cv.notify_all()

        return self._respond(
            True,
            f"Canceled {len(canceled)} event(s)",
            {"canceled": [self._event_payload(e) for e in canceled]}
        )

    def get_time_remaining(self, identifier: str) -> dict:
        ev = self._resolve_one(identifier)
        if not ev:
            return self._respond(False, f"No active timer/alarm found for '{identifier}'")

        remaining = self._time_remaining(ev)
        return self._respond(
            True,
            self._format_remaining_text(ev, remaining),
            {
                "event": self._event_payload(ev),
                "remaining_seconds": int(remaining.total_seconds())
            }
        )

    def list_active(self, kind: AlarmKind | None = None) -> dict:
        with self._cv:
            active = [
                ev for ev in self._events_by_id.values()
                if ev.state == EventState.ACTIVE and (kind is None or ev.kind == kind)
            ]
        active.sort(key=lambda e: e.run_at)
        return self._respond(
            True,
            f"{len(active)} active event(s)",
            {"events": [self._event_payload(e) for e in active]}
        )

    # ----------------------------
    # Handler integration
    # ----------------------------
    def handle_query(self, query: str):
        """
        Simple command parser (no external libs).
        Recommended: call set_timer/set_alarm/cancel/get_time_remaining directly
        from your LLM intent layer, but this is a usable fallback.
        """
        q = (query or "").strip()
        if not q:
            return self._respond(False, "Empty query")
        kind = AlarmKind.TIMER if "timer" in q else AlarmKind.ALARM

        # list
        m = re.search(r'(list|do i have)\s+(.+?)(?=\s|$|\Z)', q)
        if m:
            return self.list_active(kind=kind)

        # remaining
        m = re.search(r'(set|start|create)\s+(.+?)(?=\s|$|\Z)', q)
        if m:
            identifier = q.split(maxsplit=2)[-1].strip()
            return self.get_time_remaining(identifier)

        # cancel
        m = re.search(r'(cancel|stop|delete|remove)\s+(.+?)(?=\s|$|\Z)', q)
        if m:
            identifier = q.split(maxsplit=2)[-1].strip()
            return self.cancel(identifier)

        # set
        m = re.search(r'(set|start|create)\s+(.+?)(?=\s|$|\Z)', q)
        if m:
            if kind == AlarmKind.Timer:
                duration_s = self._parse_timer_duration(q)
                if duration_s is None:
                    return self._respond(False, "Couldn't parse timer duration. Try 'set timer for 10 minutes pasta'.")
                
                label = self._parse_timer_label(q)
                label = label if label else self._seconds_to_spoken(duration_s)
                
                return self.set_timer(duration_s, label=label)
            else:
                when_str = q[len("set alarm for "):].strip()
                run_at, label = self._parse_alarm_time_and_label(when_str)
                if run_at is None:
                    return self._respond(False, "Couldn't parse alarm time. Try 'set alarm for 07:30' or '7:30am'.")
                return self.set_alarm(run_at, label=label)

        return self._respond(False, "Unrecognized timers/alarms command", {"query": q})

    # ----------------------------
    # Internal: scheduler loop
    # ----------------------------
    def _run_loop(self):
        while True:
            with self._cv:
                if not self._running:
                    return

                while self._running and not self._heap:
                    self._cv.wait()
                if not self._running:
                    return

                run_at_epoch, _, event_id = self._heap[0]
                now_epoch = time.time()
                delay = run_at_epoch - now_epoch

                if delay > 0:
                    self._cv.wait(timeout=delay)
                    continue

                # Time to fire something (or skip stale/canceled)
                heapq.heappop(self._heap)
                ev = self._events_by_id.get(event_id)
                if not ev or ev.state != EventState.ACTIVE:
                    continue

                # Guard against stale heap entries after reschedule
                if abs(ev.run_at.timestamp() - run_at_epoch) > 0.001:
                    continue

                # Mark fired before releasing lock
                ev.state = EventState.FIRED
                self._unindex_label(ev)

            # Fire outside lock
            self._dispatch_fire(ev)

            # Handle repeats: reschedule
            if ev.repeat_interval_s:
                with self._cv:
                    if not self._running:
                        return
                    # revive as active and set next run
                    ev.state = EventState.ACTIVE
                    ev.run_at = self._now() + timedelta(seconds=ev.repeat_interval_s)
                    self._index_label(ev)
                    self._push_heap(ev)
                    self._cv.notify_all()

    def _dispatch_fire(self, ev: ScheduledEvent):
        payload = self._event_payload(ev)
        # If you have an MQTT/action bus, call it here
        if callable(self.on_fire):
            try:
                self.on_fire(payload)
            except Exception:
                # Swallow to keep scheduler alive; surface via logs in your real system
                pass

    # ----------------------------
    # Internal: indexing + heap ops
    # ----------------------------
    def _add_event(self, ev: ScheduledEvent):
        with self._cv:
            self._events_by_id[ev.id] = ev
            self._index_label(ev)
            self._push_heap(ev)
            self._cv.notify_all()

    def _push_heap(self, ev: ScheduledEvent):
        self._seq += 1
        heapq.heappush(self._heap, (ev.run_at.timestamp(), self._seq, ev.id))

    def _index_label(self, ev: ScheduledEvent):
        if ev.label:
            self._ids_by_label.setdefault(ev.label, set()).add(ev.id)

    def _unindex_label(self, ev: ScheduledEvent):
        if ev.label:
            s = self._ids_by_label.get(ev.label)
            if s:
                s.discard(ev.id)
                if not s:
                    self._ids_by_label.pop(ev.label, None)

    # ----------------------------
    # Internal: lookup
    # ----------------------------
    def _resolve(self, identifier: str) -> list[ScheduledEvent]:
        ident = (identifier or "").strip()
        if not ident:
            return []

        # Try UUID-id lookup first
        if self._is_guid(ident):
            ev = self._events_by_id.get(ident)
            return [ev] if (ev and ev.state == EventState.ACTIVE) else []

        # Label lookup
        label = self._normalize_label(ident)
        if not label:
            return []

        with self._cv:
            ids = list(self._ids_by_label.get(label, set()))
            events = [
                self._events_by_id[i] for i in ids
                if i in self._events_by_id and self._events_by_id[i].state == EventState.ACTIVE
            ]
        # Stable policy: return soonest-first
        events.sort(key=lambda e: e.run_at)
        return events

    def _resolve_one(self, identifier: str) -> ScheduledEvent | None:
        events = self._resolve(identifier)
        return events[0] if events else None

    # ----------------------------
    # Internal: parsing helpers
    # ----------------------------
    def _seconds_to_spoken(self, seconds: int) -> str:
        """
        30   -> "30 seconds"
        60   -> "1 minute"
        70   -> "1 minute and 10 seconds"
        3600 -> "1 hour"
        """
        seconds = max(0, int(seconds))

        h, rem = divmod(seconds, 3600)
        m, s = divmod(rem, 60)

        parts: list[str] = []

        def _unit(n: int, singular: str, plural: str) -> str:
            return f"{n} {singular if n == 1 else plural}"

        if h:
            parts.append(_unit(h, "hour", "hours"))
        if m:
            parts.append(_unit(m, "minute", "minutes"))
        # Say seconds if:
        # - there are no hours/minutes (pure seconds), OR
        # - seconds are non-zero
        if s and (h or m or s):
            parts.append(_unit(s, "second", "seconds"))
        elif not parts:  # 0 seconds
            parts.append("0 seconds")

        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        return f"{', '.join(parts[:-1])} and {parts[-1]}"


    def _parse_timer_label(self, text: str) -> str | None:
        """
        Extract a timer/alarm label from utterances like:
        - "set a potato timer for ten minutes"              -> "potato"
        - "set a timer for ten minutes for the potatoes"    -> "potatoes"
        - "set a timer for ten minutes named potatoes"      -> "potatoes"
        (also supports "called")

        Returns lowercase label or None if no label found.
        """
        def _clean(label: str | None) -> str | None:
            if not label:
                return None
            l = label.strip()

            # Strip surrounding quotes
            if (l.startswith(("'", '"')) and l.endswith(("'", '"')) and len(l) >= 2):
                l = l[1:-1].strip()

            # Drop trailing punctuation
            l = re.sub(r"[.!?,;:]+$", "", l).strip()

            # Remove leading determiners / fillers
            l = re.sub(r"^(?:the|a|an|my)\s+", "", l, flags=re.I).strip()

            # Remove trailing fillers
            l = re.sub(r"\s+(?:please|thanks|thank you)$", "", l, flags=re.I).strip()

            # Avoid returning empty / generic labels
            if not l or l.lower() in {"timer", "alarm"}:
                return None

            # Normalize whitespace + lowercase
            l = re.sub(r"\s+", " ", l).strip().lower()
            return l or None

        t = (text or "").strip()
        if not t:
            return None

        # 1) Explicit naming wins: "... named X" / "... called X"
        m = re.search(r"\b(?:named|called)\s+(?P<label>.+?)\s*$", t, flags=re.I)
        if m:
            return _clean(m.group("label"))

        # Find end of last duration token ("10 minutes", "two hours", etc.) to support
        # "... for ten minutes for the potatoes"
        duration_token_re = re.compile(
            r"\b(?:\d+(?:\.\d+)?|[a-z]+(?:\s+(?:[a-z]+|and))*)\s*(?:seconds?|secs?|minutes?|mins?|hours?|hrs?)\b",
            flags=re.I
        )
        last_end = 0
        for m_dur in duration_token_re.finditer(t):
            last_end = m_dur.end()

        # 2) Post-duration purpose clause: "... <duration> for (the) X"
        if last_end:
            tail = t[last_end:]
            m = re.search(r"\bfor\s+(?P<label>.+?)\s*$", tail, flags=re.I)
            if m:
                return _clean(m.group("label"))

        # 3) Adjective-before-timer form: "set a potato timer ..."
        m = re.search(r"\bset\s+(?:a|an|my)\s+(?P<label>[a-z0-9][\w\s-]*?)\s+timer\b", t, flags=re.I)
        if m:
            return _clean(m.group("label"))

        return None

    def _parse_timer_duration(self, text:str):
        prev = 0
        secs = 0

        text = text.replace("an hour and a half", "ninety minutes")
        text = text.replace("half an hour", "thirty minutes")
        text = text.replace("an hour", "one hour")
        text = text.replace("a minute", "one minute")

        token_re = re.compile(r"\s*(?P<unit>seconds?|secs?|minutes?|mins?|hours?)", re.I)
        matches = list(token_re.finditer(text))

        for m in matches:
            _slice = text[prev:m.end()]
            num = safe_word_to_num(_slice)
            prev = m.end()
            unit = m.group("unit")
            if "second" in unit:
                secs += num
            elif "minute" in unit:
                secs += num * 60
            elif "hour" in unit:
                secs += num * 3600
        
        return secs

    def _parse_alarm_time_and_label(self, s: str) -> tuple[datetime | None, str | None]:
        """
        Accepts:
        - "07:30"
        - "7:30am"
        - "7am coffee"
        Schedules for today if in future; otherwise tomorrow.
        Label = trailing non-time text.
        """
        text = (s or "").strip()
        if not text:
            return None, None

        # Extract time prefix and remainder label
        # Examples: "7am", "7:30pm", "07:30", "19:45"
        m = re.match(r"^(?P<h>\d{1,2})(:(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?\b(?P<rest>.*)$", text, re.I)
        if not m:
            return None, None

        h = int(m.group("h"))
        minute = int(m.group("m") or 0)
        ampm = (m.group("ampm") or "").lower()
        rest = (m.group("rest") or "").strip() or None

        if minute < 0 or minute > 59 or h < 0 or h > 23:
            return None, None

        if ampm:
            if h == 12:
                h = 0
            if ampm == "pm":
                h += 12
            if h > 23:
                return None, None

        now = self._now()
        candidate = now.replace(hour=h, minute=minute, second=0, microsecond=0)
        if candidate <= now:
            candidate = candidate + timedelta(days=1)

        return candidate, rest

    # ----------------------------
    # Internal: formatting + time
    # ----------------------------
    def _now(self) -> datetime:
        return datetime.now(tz=self.tz)

    def _time_remaining(self, ev: ScheduledEvent) -> timedelta:
        return max(ev.run_at - self._now(), timedelta(0))

    def _format_remaining_text(self, ev: ScheduledEvent, td: timedelta) -> str:
        secs = int(td.total_seconds())
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)

        label = f" '{ev.label}'" if ev.label else ""
        if ev.kind == AlarmKind.TIMER:
            return f"Time remaining on timer{label}: {h:02d}:{m:02d}:{s:02d}"
        return f"Time until alarm{label}: {h:02d}:{m:02d}:{s:02d}"

    def _event_payload(self, ev: ScheduledEvent) -> dict:
        return {
            "id": ev.id,
            "kind": ev.kind.value,
            "label": ev.label,
            "state": ev.state.value,
            "run_at": ev.run_at.isoformat(),
            "created_at": ev.created_at.isoformat(),
            "repeat_interval_s": ev.repeat_interval_s
        }

    def _normalize_label(self, label: str | None) -> str | None:
        if not label:
            return None
        l = label.strip().lower()
        return l or None

    def _is_guid(self, s: str) -> bool:
        if not self._UUID_RE.match(s):
            return False
        try:
            uuid.UUID(s)
            return True
        except Exception:
            return False
