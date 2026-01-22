import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .llm import LLMManager
from .tts import WyomingTtsClient
from .asr import ASR
from .triage import UtteranceCategorizer
from .handlers import Clock, Weather

USER_AGENT = "custom-home-assistant (aaronbastian31@gmail.com)"


class CoreService:
    def __init__(
        self,
        voice: str = "glados_classic",
        tts_uri: str = "tcp://127.0.0.1:10200",
        tts_start_timeout: float = 5.0,
        llm_base_url: str = "http://127.0.0.1:11434",
        llm_model: Optional[str] = None,
        llm_auto_start: bool = True,
        llm_auto_pull: bool = False,
    ):
        self.default_voice = voice
        self.tts_uri = tts_uri
        self.tts_client = WyomingTtsClient(tts_uri, timeout=tts_start_timeout)
        self.tts_process: Optional[subprocess.Popen] = None
        self._owns_tts_process = False
        if not self.tts_client.try_connect():
            self.tts_process = self._start_tts_server(voice, tts_uri)
            self._owns_tts_process = True
            self.tts_client.wait_until_ready()
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
        self.clock = Clock(user_agent=USER_AGENT)
        self.weather = Weather(user_agent=USER_AGENT)

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

        if (self.tts_process is None) or (not self._owns_tts_process):
            return

        self.tts_process.terminate()
        try:
            self.tts_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.tts_process.kill()
            self.tts_process.wait()

        self.tts_process = None
        self._owns_tts_process = False

    def stop_all(self) -> None:
        self.stop()
        if self.llm_manager is not None:
            self.llm_manager.stop()

    def _start_tts_server(self, voice: str, uri: str) -> subprocess.Popen:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "core.tts.tts_wyoming",
                "--voice",
                voice,
                "--uri",
                uri,
            ],
        )
