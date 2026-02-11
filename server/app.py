from flask import Flask, request
from core import CoreService
from core.llm import LlmBenchmarkRunner
from core.networking import get_preferred_ip

preferred_ip = get_preferred_ip()
service = CoreService(
    tts_uri=f"tcp://{preferred_ip}:10200",
    llm_base_url=f"http://{preferred_ip}:11434",
)
benchmark_runner = LlmBenchmarkRunner(base_url=service.llm_manager.base_url)
app = Flask(__name__)

@app.post("/api/audio")
def handle_audio():
    file = request.files["file"]
    result = service.handle_audio(file)
    return {"text": result}

@app.get("/api/status")
def status():
    return service.status()


@app.post("/api/llm/benchmark")
def llm_benchmark():
    payload = request.get_json(silent=True) or {}
    model = payload.get("model") or service.llm_manager.model
    prompts = payload.get("prompts")

    if not model:
        return {"error": "model is required"}, 400

    service.llm_manager.ensure_running()
    result = benchmark_runner.run(model=model, prompts=prompts)
    return result


@app.get("/api/llm/benchmark/latest")
def llm_benchmark_latest():
    result = benchmark_runner.latest()
    if result is None:
        return {"error": "no benchmark results yet"}, 404
    return result


@app.get("/api/llm/models")
def llm_models():
    try:
        return benchmark_runner.list_models()
    except Exception as exc:
        return {"error": str(exc)}, 502
