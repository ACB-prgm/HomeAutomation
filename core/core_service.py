import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urlunparse

from .llm import LLMManager
from .tts import WyomingTtsClient
from .asr import ASR
from .triage import UtteranceCategorizer
from .networking import get_preferred_ip
# from .handlers import Clock, Weather

USER_AGENT = "custom-home-assistant (aaronbastian31@gmail.com)"


def _swap_localhost(url: str, new_host: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname
    if host not in {"127.0.0.1", "localhost", "::1"}:
        return url
    port = parsed.port
    netloc = f"{new_host}:{port}" if port else new_host
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def _connect_uri(uri: str, timeout: float = 1.0) -> None:
    parsed = urlparse(uri)
    if parsed.scheme == "tcp":
        host = parsed.hostname or "127.0.0.1"
        if parsed.port is None:
            raise ValueError("tcp:// uri requires a port")
        sock = socket.create_connection((host, parsed.port), timeout=timeout)
        sock.close()
        return

    if parsed.scheme == "unix":
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect(parsed.path)
        finally:
            sock.close()
        return

    raise ValueError("Only tcp:// or unix:// URIs are supported")


def _can_connect(uri: str, timeout: float = 1.0) -> bool:
    try:
        _connect_uri(uri, timeout=timeout)
        return True
    except OSError:
        return False


def _wait_until_ready(uri: str, timeout: float, service_name: str) -> None:
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            _connect_uri(uri, timeout=0.5)
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.2)

    raise RuntimeError(f"{service_name} server not ready at {uri}") from last_error


class CoreService:
    def __init__(
        self,
        voice: str = "glados_classic",
        tts_uri: str = "tcp://127.0.0.1:10200",
        tts_start_timeout: float = 5.0,
        asr_uri: str = "tcp://127.0.0.1:10300",
        asr_start_timeout: float = 5.0,
        llm_base_url: str = "http://127.0.0.1:11434",
        llm_model: Optional[str] = None,
        llm_auto_start: bool = True,
        llm_auto_pull: bool = False,
    ):
        preferred_ip = get_preferred_ip()
        tts_uri = _swap_localhost(tts_uri, preferred_ip)
        asr_uri = _swap_localhost(asr_uri, preferred_ip)
        llm_base_url = _swap_localhost(llm_base_url, preferred_ip)

        self.default_voice = voice
        self.tts_uri = tts_uri
        self.asr_uri = asr_uri
        self.tts_client = WyomingTtsClient(tts_uri, timeout=tts_start_timeout)
        self.tts_process: Optional[subprocess.Popen] = None
        self.asr_process: Optional[subprocess.Popen] = None
        self._owns_tts_process = False
        self._owns_asr_process = False
        if not self.tts_client.try_connect():
            self.tts_process = self._start_tts_server(voice, tts_uri)
            self._owns_tts_process = True
            self.tts_client.wait_until_ready()
        if not _can_connect(asr_uri, timeout=0.5):
            self.asr_process = self._start_asr_server(asr_uri)
            self._owns_asr_process = True
            _wait_until_ready(asr_uri, timeout=asr_start_timeout, service_name="ASR")
        self.llm_manager = LLMManager(
            base_url=llm_base_url,
            model=llm_model,
            auto_start=llm_auto_start,
        )
        if llm_auto_start:
            self.llm_manager.ensure_running()
        if llm_auto_pull and llm_model:
            self.llm_manager.ensure_model(llm_model)
        self.asr = ASR()
        self.triager = UtteranceCategorizer()
        # self.clock = Clock(user_agent=USER_AGENT)
        # self.weather = Weather(user_agent=USER_AGENT)

        print(f"[+] TTS URI: {self.tts_uri}")
        print(f"[+] ASR URI: {self.asr_uri}")
        print(f"[+] LLM base URL: {self.llm_manager.base_url}")

    def handle_query(self, query: str, debug:bool = False):
        category, cleaned_query = self.triager.categorize(query)

        if category == "Other":
            response = self.llm_handle(cleaned_query)
        else:
            # get the class instance made to handle queries of this type.
            response = self.__getattribute__(category.lower()).handle_query(cleaned_query)

        if debug:
            for x in [category, cleaned_query, response]:
                print(x)
        
        return self.tts_client.synthesize(response["text"], voice_name=self.default_voice)
    
    def llm_handle(query:str):
        return ""

    def handle_audio(self, file_obj) -> str:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            file_obj.save(tmp_file.name)
            tmp_path = tmp_file.name

        try:
            return self.asr.transcribe(tmp_path)
        finally:
            try:
                Path(tmp_path).unlink()
            except FileNotFoundError:
                pass

    def stop(self) -> None:
        if self.tts_client is not None:
            self.tts_client.close()

        if (self.tts_process is not None) and self._owns_tts_process:
            self.tts_process.terminate()
            try:
                self.tts_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.tts_process.kill()
                self.tts_process.wait()

            self.tts_process = None
            self._owns_tts_process = False

        if (self.asr_process is not None) and self._owns_asr_process:
            self.asr_process.terminate()
            try:
                self.asr_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.asr_process.kill()
                self.asr_process.wait()

            self.asr_process = None
            self._owns_asr_process = False

    def stop_all(self) -> None:
        self.stop()
        if self.llm_manager is not None:
            self.llm_manager.stop()

    def _start_tts_server(self, voice: str, uri: str) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "core.tts.tts_wyoming_server",
                "--voice",
                voice,
                "--uri",
                uri,
                "--no-streaming",
            ],
        )

    def _start_asr_server(self, uri: str) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "core.asr.asr_wyoming_server",
                "--uri",
                uri,
            ],
        )
