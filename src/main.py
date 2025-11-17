import os
import json
import httpx
import logging
import base64
import wave
import io
import pydantic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import Response, StreamingResponse
from typing import Literal
from dotenv import load_dotenv

load_dotenv()

# Kendi modüllerimizi 'src' dizininden import ediyoruz
from .stt_module.stt_service import STTService

# --- Loglama Ayarları ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- API Anahtarı ---
# GÜVENLİK: Bu anahtarı kodun içine yazmak yerine ortam değişkeni (environment variable) olarak ayarlayın
# export GEMINI_API_KEY="AIza..."
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE")

if GEMINI_API_KEY == "YOUR_API_KEY_HERE":
    logger.warning("GEMINI_API_KEY ortam değişkeni ayarlanmamış. Lütfen API anahtarınızı ayarlayın.")

IS_PYDANTIC_V2 = pydantic.VERSION.startswith("2.")

app = FastAPI(
    title="Holographic AI Assistant API",
    description="Gerçek zamanlı STT, LLM Intent ve TTS servisleri."
)

# --- Veri Modelleri (Pydantic) ---
class IntentRequest(pydantic.BaseModel):
    text: str

class SynthesisRequest(pydantic.BaseModel):
    text: str
    voice: str = "Kore" # Varsayılan ses

class ClinicIntentResponse(pydantic.BaseModel):
    poliklinik: str
    aciliyet: Literal["acil", "normal", "acil değil"]
    sebep_ozeti: str

# --- LLM API Fonksiyonu ---
async def fetch_llm_intent(text: str) -> ClinicIntentResponse:
    """
    Verilen metni analiz etmesi için Gemini LLM'e gönderir.
    Yapılandırılmış JSON (ClinicIntentResponse) döndürür.
    """
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_API_KEY_HERE":
        logger.error("LLM İsteği Başarısız: GEMINI_API_KEY eksik.")
        raise HTTPException(status_code=500, detail="Sunucuda API anahtarı yapılandırılmamış.")

    API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key={GEMINI_API_KEY}"
    
    # Hastane asistanı rolü ve JSON zorlaması
    system_prompt = (
        "Sen bir hastane karşılama asistanısın. Görevin, hastanın şikayetini analiz edip "
        "onu *sadece* doğru polikliniğe yönlendirmektir. Tıbbi tavsiye verme, 'geçmiş olsun' deme. "
        "Cevabını *sadece* istenen JSON formatında ver. "
        "Eğer şikayet belirsizse 'poliklinik' alanını 'Belirsiz' olarak ayarla."
    )
    
    payload = {
        "contents": [{"parts": [{"text": text}]}],
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": ClinicIntentResponse.model_json_schema()
        }
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            logger.info(f"LLM İsteği Gönderiliyor (URL: ...flash-preview...): {text}")
            response = await client.post(url, json=payload)
            logger.info(f"LLM Yanıt Durumu: {response.status_code}")
            
            # API'den gelen hatayı logla ve düzgün bir hata fırlat
            if response.status_code != 200:
                 logger.error(f"LLM API Hatası (HTTP {response.status_code}): {response.text}")
                 response.raise_for_status() # HTTP 4xx/5xx hatası varsa exception fırlat
            
            # Gemini'den gelen yanıtın içindeki JSON metnini parse et
            raw_response_data = response.json()
            json_text = raw_response_data["candidates"][0]["content"]["parts"][0]["text"]
            parsed_json = json.loads(json_text)
            
            # Pydantic v1/v2 uyumlu parse etme ve döndürme
            if IS_PYDANTIC_V2:
                return ClinicIntentResponse(**parsed_json)
            else:
                return ClinicIntentResponse.parse_obj(parsed_json)
            
    except httpx.HTTPStatusError as e:
        logger.error(f"LLM API Hatası (HTTP {e.response.status_code}): {e.response.text}")
        raise HTTPException(status_code=500, detail=f"LLM servisi hatası: {e.response.text}")
    except (httpx.RequestError, json.JSONDecodeError, KeyError, pydantic.ValidationError) as e:
        logger.error(f"LLM İsteği Başarısız: {e}")
        raise HTTPException(status_code=500, detail=f"LLM servisine ulaşılamadı veya yanıtı geçersiz: {e}")


# --- API Endpoint 1: Intent (LLM Analizi) ---

@app.post("/api/get_intent", response_model=ClinicIntentResponse)
async def get_intent_endpoint(request: IntentRequest):
    """
    Bir metin alır, LLM ile analiz eder ve poliklinik yönlendirmesini JSON olarak döner.
    """
    logger.info(f"Intent İsteği Alındı: '{request.text}'")
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Metin boş olamaz.")
        
    intent_data = await fetch_llm_intent(request.text)
    logger.info(f"Intent Sonucu: {intent_data.model_dump_json(ensure_ascii=False)}")
    return intent_data

# --- API Endpoint 2: Synthesize (TTS) ---

@app.post("/api/synthesize")
async def synthesize_endpoint(request: SynthesisRequest):
    """
    Bir metin alır, Gemini TTS ile sese dönüştürür ve WAV dosyası olarak döndürür.
    """
    logger.info(f"TTS İsteği Alındı: '{request.text}' (Ses: {request.voice})")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "YOUR_API_KEY_HERE":
        logger.error("TTS İsteği Başarısız: GEMINI_API_KEY eksik.")
        raise HTTPException(status_code=500, detail="Sunucuda API anahtarı yapılandırılmamış.")

    API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-tts:generateContent?key={GEMINI_API_KEY}"
    
    payload = {
        "contents": [{"parts": [{"text": request.text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": request.voice}}
            }
        },
        "model": "gemini-2.5-flash-preview-tts"
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(API_URL, json=payload, headers={"Content-Type": "application/json"})
            response.raise_for_status()

            res_json = response.json()
            part = res_json["candidates"][0]["content"]["parts"][0]
            audio_data_base64 = part["inlineData"]["data"]
            mime_type = part["inlineData"]["mimeType"] # "audio/L16;rate=24000"
            
            sample_rate = int(mime_type.split("rate=")[1])
            audio_data_pcm = base64.b64decode(audio_data_base64)

            # Ham PCM verisini WAV formatına dönüştür
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wf:
                wf.setnchannels(1)  # Mono
                wf.setsampwidth(2)  # 16-bit PCM (L16)
                wf.setframerate(sample_rate)
                wf.writeframes(audio_data_pcm)
            
            wav_buffer.seek(0)
            logger.info(f"TTS Başarılı: {len(wav_buffer.getvalue())} bytes WAV oluşturuldu.")
            return Response(content=wav_buffer.getvalue(), media_type="audio/wav")

    except Exception as e:
        logger.error(f"TTS İsteği Başarısız: {e}")
        raise HTTPException(status_code=500, detail=f"TTS servisi hatası: {e}")

# --- API Endpoint 3: Gerçek Zamanlı STT (WebSocket) ---

@app.websocket("/ws/stream_stt")
async def websocket_stt_endpoint(websocket: WebSocket, sample_rate: int = 16000):
    """
    Aktif dinleyici (STT) WebSocket endpoint'i.
    İstemciden (örn. tarayıcı, mobil) gelen ham ses (PCM) akışını alır.
    Sesi gerçek zamanlı olarak metne döker.
    Kısmi (partial) ve nihai (final) transkriptleri JSON olarak geri gönderir.
    """
    await websocket.accept()
    logger.info(f"WebSocket bağlantısı kabul edildi (Rate: {sample_rate}).")
    
    try:
        # Her bağlantı için yeni, stateful bir STTService başlat
        stt_service = STTService(sample_rate=sample_rate)
        
        # WebSocket üzerinden gelen ses 'chunk'larını dinle
        while True:
            # Not: Tarayıcılar genelde 'bytes' yollar, Python istemcileri de 'bytes' yollamalı
            audio_chunk = await websocket.receive_bytes()
            
            # Gelen 'chunk'ı işle
            result = stt_service.transcribe_chunk(audio_chunk)
            
            # Sadece anlamlı bir metin varsa (boş değilse) istemciye gönder
            if result and result.get("text"):
                await websocket.send_json(result)
                
                # Eğer nihai sonuçsa logla
                if result.get("type") == "final":
                    logger.info(f"WebSocket Nihai Transkript: '{result['text']}'")

    except WebSocketDisconnect:
        logger.warning("WebSocket bağlantısı kapandı (Disconnect).")
        # (Opsiyonel: Bağlantı koptuğunda eldeki son veriyi de gönderebilirsiniz)
        # last_result = stt_service.get_final_result()
        # if last_result and last_result.get("text"):
        #     await websocket.send_json(last_result)
            
    except Exception as e:
        logger.error(f"WebSocket Hatası: {e}")
        # Hata durumunda istemciye bir hata mesajı göndermeyi deneyin
        try:
            await websocket.close(code=1011, reason=f"Sunucu hatası: {e}")
        except:
            pass # Bağlantı zaten kopmuşsa (örn. VADİ hatası) pass geç


# Basit kök (root) endpoint — 404'leri önlemek için
@app.get("/")
async def root():
    """
    Kök (root) endpoint. Uygulamanın çalıştığını ve Swagger UI adresini gösterir.
    """
    return {"message": "Holographic AI Assistant API çalışıyor.", "docs": "/docs"}


# Basit favicon yanıtı (tarayıcıların favicon isteği 404 döndürmesin diye)
@app.get("/favicon.ico")
async def favicon():
    # 204 No Content döndürmek en basitidir; isterseniz gerçek bir ikon döndürebilirsiniz.
    return Response(status_code=204)
