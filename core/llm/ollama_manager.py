import os
import subprocess
import time
from shutil import which
from typing import Optional
from urllib.parse import urlparse

import requests


class LLMManager:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: Optional[str] = None,
        auto_start: bool = True,
        timeout: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.auto_start = auto_start
        self.timeout = timeout
        self._process: Optional[subprocess.Popen] = None
        self._owns_process = False

    def ensure_running(self) -> bool:
        if self.is_running():
            return True

        if (not self.auto_start) or (not self._can_start()):
            return False

        parsed = urlparse(self.base_url)
        port = parsed.port or 11434
        env = os.environ.copy()
        env["OLLAMA_HOST"] = f"0.0.0.0:{port}"
        self._process = subprocess.Popen(["ollama", "serve"], env=env)
        self._owns_process = True
        return self._wait_until_ready()

    def ensure_model(self, model: Optional[str] = None) -> None:
        model_name = model or self.model
        if not model_name:
            return

        if not self._ollama_available():
            raise RuntimeError("ollama is not installed or not on PATH")

        if not self.is_running():
            if not self.ensure_running():
                raise RuntimeError("Ollama server is not running")

        if self._model_available(model_name):
            return

        subprocess.run(["ollama", "pull", model_name], check=True)

    def is_running(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/version", timeout=self.timeout)
        except requests.RequestException:
            return False

        return resp.ok

    def stop(self) -> None:
        if not self._owns_process or (self._process is None):
            return

        self._process.terminate()
        try:
            self._process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait()

        self._process = None
        self._owns_process = False

    def _wait_until_ready(self) -> bool:
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            if self.is_running():
                return True
            time.sleep(0.2)

        return False

    def _model_available(self, model_name: str) -> bool:
        result = subprocess.run(
            ["ollama", "list"], capture_output=True, text=True
        )
        if result.returncode != 0:
            return False

        for line in result.stdout.splitlines()[1:]:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == model_name:
                return True

        return False

    def _ollama_available(self) -> bool:
        return which("ollama") is not None

    def _can_start(self) -> bool:
        return self._ollama_available()