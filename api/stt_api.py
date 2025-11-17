from fastapi import FastAPI, UploadFile
from stt_module.stt_service import STTService

app = FastAPI()
stt = STTService()

@app.post("/transcribe")
async def transcribe_audio(file: UploadFile):
    path = f"data/{file.filename}"
    with open(path, "wb") as f:
        f.write(await file.read())
    result = stt.transcribe(path)
    return {"text": result.get("text", "")}
