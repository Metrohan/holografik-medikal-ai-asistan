# Holographic AI Assistant (Holografik Medikal Asistan)

Kısa: Gerçek zamanlı STT (Vosk), LLM tabanlı intent analizi (Gemini gibi) ve TTS uç noktalarına sahip FastAPI tabanlı küçük bir servis iskeleti.

Bu repo, klinik yönlendirme amaçlı bir asistan denemesi içerir: mikrofon veya dosya ile gelen sesin metne çevrilmesi, metnin LLM ile analiz edilip polikliniğe yönlendirilmesi ve TTS ile cevap oluşturulması gibi işlevleri barındırır.

## İçindekiler

- `src/main.py` — FastAPI uygulaması, WebSocket STT endpoint'i ve LLM/TTS örnek endpoint'leri.
- `src/stt_module/` — Vosk tabanlı STT servisi (`STTService`) ve model klasörü beklenir.
- `api/stt_api.py` — basit dosya-yükleme örneği (uygulamada küçük farklılıklar olabilir).
- `data/` — örnek sesler ve sunucuya kaydedilen yüklemeler için (varsa).
- `tests/` — bazı test senaryoları.

## Gereksinimler

- Python 3.9+ (tercihen 3.10/3.11)
- Önerilen paketler (projede `requirements.txt` boş ise elle kur):

```bash
pip install fastapi "uvicorn[standard]" httpx python-dotenv pydantic vosk websockets
```

Not: `vosk` paketi ve Vosk modelleri platforma göre ilave bağımlılıklar/dosyalar gerektirebilir.

## Kurulum

1. Proje kökünde sanal ortam oluştur ve aktif et:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
```

2. Gerekli paketleri yükle (bak: Gereksinimler):

```bash
pip install -r requirements.txt
# Eğer requirements.txt boşsa:
pip install fastapi "uvicorn[standard]" httpx python-dotenv pydantic vosk
```

3. (Zorunlu) Vosk TR modeli:

Projede `src/stt_module/models/vosk-model-small-tr-0.3` dizini aranır. Eğer yoksa Vosk Türkçe küçük modeli indirip bu dizine koymalısınız. Aksi halde STT servis başlatılırken `FileNotFoundError` alırsınız.

## Ortam değişkenleri

- `GEMINI_API_KEY` — LLM ve TTS çağrıları için gerekli (örn. Gemini API). Geliştirme için `.env` dosyası oluşturabilirsiniz:

```
GEMINI_API_KEY=your_api_key_here
```

`python-dotenv` otomatik olarak yüklendiği için `src/main.py` bu dosyayı okur.

## Uygulamayı çalıştırma (geliştirme)

Kök dizinden:

```bash
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000
```

Ardından tarayıcıda `http://127.0.0.1:8000/docs` adresinden Swagger UI'ı görebilirsiniz.

## Önemli endpoint'ler

- `POST /api/get_intent` — JSON `{ "text": "..." }` gönder, LLM ile analiz sonucu (poliklinik, aciliyet, özet) döner.
- `POST /api/synthesize` — `{ "text": "...", "voice": "Kore" }` gönder, WAV döner (TTS).
- `WebSocket /ws/stream_stt` — gerçek zamanlı STT: istemci binary (PCM16) parçaları gönderir, sunucu kısmi/nihai transkriptleri JSON olarak geri yollar.
- `POST /transcribe` (basit dosya yükleme) — `api/stt_api.py` içinde örnek var; fakat mevcut `STTService` API ile uyumlu olmayabilir. Eğer hata alırsanız bu endpoint'in `STTService`'e uygun hale getirilmesi gerekir (repo içinde örnek düzeltme yapılabilir).

## Nasıl ses gönderirim? (kısa rehber)

1) WebSocket (gerçek zamanlı):

- Tarayıcıdan: `getUserMedia` -> `AudioContext` ile alınan Float32 veriyi Int16'ya çevirip WebSocket'e gönderin. Sunucu `ws/stream_stt` bu binary chunk'ları bekler.
- Python istemci ile WAV stream etme örneği:

```python
# pip install websockets
import asyncio, wave, websockets

async def stream_wav(filepath, url="ws://127.0.0.1:8000/ws/stream_stt?sample_rate=16000"):
	async with websockets.connect(url) as ws:
		with wave.open(filepath, "rb") as wf:
			assert wf.getsampwidth() == 2
			while True:
				data = wf.readframes(4096)
				if not data:
					break
				await ws.send(data)
				try:
					resp = await asyncio.wait_for(ws.recv(), timeout=0.1)
					print('Sunucudan:', resp)
				except asyncio.TimeoutError:
					pass

asyncio.run(stream_wav('ses_ornegi.wav'))
```

2) HTTP dosya yükleme (tek seferlik):

```bash
curl -F "file=@ses_ornegi.wav" http://127.0.0.1:8000/transcribe
```

Not: `api/stt_api.py` sunucuda dosyayı `data/` içine kaydedip `stt.transcribe(path)` çağırıyor — eğer `STTService`'de `transcribe(path)` yoksa bu endpoint çalışmayacaktır. Gerekirse repo'ya uyumlu bir `upload_transcribe` endpoint'i ekleyebilirim.

## Hata/Çözümler

- 404 at `GET /` veya `/favicon.ico`: Bu repo için `src/main.py` artık kök endpoint (`/`) döndürüyor ve `/favicon.ico` için 204 Response veriyor.
- Vosk model bulunamadı hatası: `src/stt_module/models/vosk-model-small-tr-0.3` klasörünü kontrol edin.
- LLM/TTS hataları: `GEMINI_API_KEY` ortam değişkeninin doğru olduğundan emin olun.

## Testler

Projede bazı pytest testleri bulunuyor (`tests/`). Hızlıca çalıştırmak için:

```bash
pip install pytest
pytest -q
```

## Katkıda bulunma

İstersen küçük PR'lar ile iyileştirmeler kabul edilir: README güncellemeleri, endpoint düzeltmeleri (örn. `/transcribe` uyumluluğu), ek testler.

## Lisans

Bu repo için lisans bilgisi eklenmemiş. Kendi kullanımına göre bir lisans eklemeyi düşün.

---

Eğer istersen, ben `api/stt_api.py`'yi `STTService` ile uyumlu hale getirecek bir `upload_transcribe` endpoint'i ekleyebilirim ve bir örnek `curl` testi çalıştırabilirim. Hangisini istersin?

