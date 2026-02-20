from __future__ import annotations

import json
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


DEFAULT_IDENTITY_PATH = Path("/var/lib/satellite/identity.json")


def _read_pi_serial() -> Optional[str]:
	"""
	Best-effort read of Raspberry Pi SoC serial.
	Returns None if unavailable (non-Pi, container, etc.).
	"""
	try:
		with open("/proc/cpuinfo", "r") as f:
			for line in f:
				if line.startswith("Serial"):
					return line.split(":")[1].strip()
	except FileNotFoundError:
		pass

	return None


@dataclass(frozen=True)
class Identity:
	satellite_id: str
	serial: str
	created_at: str


class IdentityManager:
	"""
	Responsible for loading or creating a persistent satellite identity.

	This module must:
	- run early
	- have no external dependencies
	- never regenerate identity once created
	"""

	def __init__(self, path: Path = DEFAULT_IDENTITY_PATH):
		self._path = Path(path)
		self._identity: Identity | None = None

	def load(self) -> Identity:
		"""
		Load identity from disk, or create it if missing.
		This method is idempotent.
		"""
		if self._identity is not None:
			return self._identity

		if self._path.exists():
			self._identity = self._load_existing()
		else:
			self._identity = self._create_new()

		return self._identity

	def _load_existing(self) -> Identity:
		with open(self._path, "r") as f:
			data = json.load(f)

		return Identity(
			satellite_id=data["satellite_id"],
			serial=data.get("serial", ""),
			created_at=data["created_at"],
		)

	def _create_new(self) -> Identity:
		self._path.parent.mkdir(parents=True, exist_ok=True)

		identity = Identity(
			satellite_id=f"sat-{uuid.uuid4()}",
			serial=_read_pi_serial(),
			created_at=datetime.now(timezone.utc).isoformat(),
		)

		with open(self._path, "w") as f:
			json.dump(asdict(identity), f, indent=2)

		return identity

	@property
	def identity(self) -> Identity:
		if self._identity is None:
			raise RuntimeError("Identity not loaded yet. Call load().")
		return self._identity
