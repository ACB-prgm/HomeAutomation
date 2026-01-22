import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests


_DEFAULT_PROMPTS: List[str] = [
    "Summarize this text in one sentence: The quick brown fox jumps over the lazy dog.",
    "Explain how a thermostat works in two sentences.",
    "List three benefits of using a local voice assistant.",
]


@dataclass
class BenchmarkResult:
    model: str
    base_url: str
    started_at: str
    finished_at: str
    prompts: List[Dict[str, Any]]
    aggregate: Dict[str, Any]


class LlmBenchmarkRunner:
    def __init__(
        self,
        base_url: str,
        storage_path: Optional[Path] = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.storage_path = storage_path or (
            Path(__file__).resolve().parent / "benchmarks.json"
        )
        self.timeout = timeout

    def run(
        self,
        model: str,
        prompts: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        prompts_list = list(prompts) if prompts else list(_DEFAULT_PROMPTS)
        started = self._timestamp()
        prompt_results: List[Dict[str, Any]] = []

        for prompt in prompts_list:
            response = self._generate(model, prompt)
            metrics = self._extract_metrics(response)
            prompt_results.append(
                {
                    "prompt": prompt,
                    "model": response.get("model", model),
                    **metrics,
                }
            )

        finished = self._timestamp()
        aggregate = self._aggregate(prompt_results)
        result = BenchmarkResult(
            model=model,
            base_url=self.base_url,
            started_at=started,
            finished_at=finished,
            prompts=prompt_results,
            aggregate=aggregate,
        )
        self._store_result(result)
        return self._as_dict(result)

    def latest(self) -> Optional[Dict[str, Any]]:
        data = self._load_storage()
        latest = data.get("latest")
        if latest:
            return latest
        return None

    def list_models(self) -> Dict[str, Any]:
        resp = requests.get(f"{self.base_url}/api/tags", timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()

    def _generate(self, model: str, prompt: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def _extract_metrics(self, response: Dict[str, Any]) -> Dict[str, Any]:
        prompt_eval_count = response.get("prompt_eval_count")
        eval_count = response.get("eval_count")
        prompt_eval_duration = response.get("prompt_eval_duration")
        eval_duration = response.get("eval_duration")
        total_duration = response.get("total_duration")

        prompt_eval_tps = self._tokens_per_second(
            prompt_eval_count, prompt_eval_duration
        )
        eval_tps = self._tokens_per_second(eval_count, eval_duration)

        return {
            "prompt_eval_count": prompt_eval_count,
            "eval_count": eval_count,
            "prompt_eval_duration_ns": prompt_eval_duration,
            "eval_duration_ns": eval_duration,
            "total_duration_ns": total_duration,
            "prompt_eval_tps": prompt_eval_tps,
            "eval_tps": eval_tps,
        }

    def _aggregate(self, prompt_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        prompt_tokens = sum(
            r.get("prompt_eval_count") or 0 for r in prompt_results
        )
        eval_tokens = sum(r.get("eval_count") or 0 for r in prompt_results)
        prompt_time_ns = sum(
            r.get("prompt_eval_duration_ns") or 0 for r in prompt_results
        )
        eval_time_ns = sum(r.get("eval_duration_ns") or 0 for r in prompt_results)

        return {
            "prompt_eval_count": prompt_tokens,
            "eval_count": eval_tokens,
            "prompt_eval_duration_ns": prompt_time_ns,
            "eval_duration_ns": eval_time_ns,
            "prompt_eval_tps": self._tokens_per_second(
                prompt_tokens, prompt_time_ns
            ),
            "eval_tps": self._tokens_per_second(eval_tokens, eval_time_ns),
        }

    def _tokens_per_second(self, tokens: Any, duration_ns: Any) -> Optional[float]:
        if not tokens or not duration_ns:
            return None
        seconds = float(duration_ns) / 1_000_000_000.0
        if seconds <= 0:
            return None
        return round(float(tokens) / seconds, 3)

    def _store_result(self, result: BenchmarkResult) -> None:
        data = self._load_storage()
        entry = self._as_dict(result)
        history = data.get("history", [])
        history.append(entry)
        data["history"] = history
        data["latest"] = entry
        self._write_storage(data)

    def _load_storage(self) -> Dict[str, Any]:
        if not self.storage_path.exists():
            return {"latest": None, "history": []}

        try:
            with self.storage_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"latest": None, "history": []}

    def _write_storage(self, data: Dict[str, Any]) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _as_dict(self, result: BenchmarkResult) -> Dict[str, Any]:
        return {
            "model": result.model,
            "base_url": result.base_url,
            "started_at": result.started_at,
            "finished_at": result.finished_at,
            "prompts": result.prompts,
            "aggregate": result.aggregate,
        }
