from __future__ import annotations

import logging
from typing import Optional


DEFAULT_LOG_FIELDS = {
	"satellite_id": "-",
	"session_id": "-",
	"pipeline_run_id": "-",
	"room": "-",
}


class _StructuredFieldFilter(logging.Filter):
	def filter(self, record: logging.LogRecord) -> bool:
		for key, value in DEFAULT_LOG_FIELDS.items():
			if not hasattr(record, key):
				setattr(record, key, value)
		return True


def configure_logging(level: str = "INFO") -> None:
	logging.basicConfig(
		level=getattr(logging, level.upper(), logging.INFO),
		format=(
			"%(asctime)s %(levelname)s %(name)s "
			"satellite_id=%(satellite_id)s session_id=%(session_id)s "
			"pipeline_run_id=%(pipeline_run_id)s room=%(room)s %(message)s"
		),
		force=True,
	)
	root = logging.getLogger()
	filter_installed = any(isinstance(f, _StructuredFieldFilter) for f in root.filters)
	if not filter_installed:
		root.addFilter(_StructuredFieldFilter())


def context_extra(
	satellite_id: Optional[str] = None,
	room: Optional[str] = None,
	session_id: Optional[str] = None,
	pipeline_run_id: Optional[str] = None,
) -> dict[str, str]:
	extra = dict(DEFAULT_LOG_FIELDS)
	if satellite_id:
		extra["satellite_id"] = satellite_id
	if room:
		extra["room"] = room
	if session_id:
		extra["session_id"] = session_id
	if pipeline_run_id:
		extra["pipeline_run_id"] = pipeline_run_id
	return extra
