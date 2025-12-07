from flask import Flask, request
from core import CoreService

service = CoreService()
app = Flask(__name__)

@app.post("/api/audio")
def handle_audio():
    file = request.files["file"]
    result = service.handle_audio(file)
    return {"text": result}

@app.get("/api/status")
def status():
    return service.status()
