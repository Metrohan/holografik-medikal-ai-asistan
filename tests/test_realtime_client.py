import asyncio
import websockets
import wave
import json
import httpx
import os
import subprocess

# --- AYARLAR ---
SERVER_WS_URL = "ws://127.0.0.1:8000/ws/stream_stt"
SERVER_API_URL = "http://127.0.0.1:8000/api"

# Test için kullanılacak ses dosyası (16000Hz, 16-bit, Mono olmalı)
# Vosk modelimizin (small-tr) en iyi çalıştığı format budur.
# NOT: test_fixed3.wav dosyanız bu formatta değilse bu script HATA VEREBİLİR.
# Gerekirse `ffmpeg -i input.wav -ar 16000 -ac 1 -c:a pcm_s16le output_16k.wav` ile çevirin.
INPUT_AUDIO_FILE = "data/samples/test_fixed3.wav" # Bu dosyanın 16000Hz olduğunu varsayıyoruz
SAMPLE_RATE = 16000
CHUNK_SIZE = 4000  # Her seferinde kaç byte gönderileceği (küçültebilirsiniz)

OUTPUT_AUDIO_FILE = "tests/response_realtime.wav"
# --- AYARLAR BİTTİ ---

async def run_realtime_flow():
    """
    Tüm gerçek zamanlı akışı test eder:
    1. WebSocket ile ses akışı gönderir -> Nihai transkript alır.
    2. Transkripti /api/get_intent'e yollar -> JSON alır.
    3. JSON'a göre cevap cümlesi kurar -> /api/synthesize'a yollar.
    4. Gelen sesi dosyaya yazar ve çalar.
    """
    
    final_transcript = ""

    # --- 1. Adım: WebSocket STT Akışı ---
    print(f"--- 1. Adım: WebSocket Bağlantısı Başlatılıyor ({SERVER_WS_URL}) ---")
    try:
        # Ses dosyasının sample rate'ini kontrol et
        with wave.open(INPUT_AUDIO_FILE, 'rb') as wf:
            if wf.getframerate() != SAMPLE_RATE:
                print(f"HATA: Ses dosyasının sample rate'i ({wf.getframerate()}Hz) "
                      f"beklenenle ({SAMPLE_RATE}Hz) uyuşmuyor.")
                print("Lütfen dosyayı 16000Hz'e çevirin (ffmpeg komutu yorum satırında).")
                return
            if wf.getsampwidth() != 2 or wf.getnchannels() != 1:
                print("HATA: Ses dosyası 16-bit, Mono PCM formatında olmalı.")
                return

        # WebSocket bağlantısını, sample rate parametresiyle birlikte aç
        async with websockets.connect(f"{SERVER_WS_URL}?sample_rate={SAMPLE_RATE}") as websocket:
            print(f"Bağlantı başarılı. '{INPUT_AUDIO_FILE}' dosyası stream ediliyor...")
            
            # Ses dosyasını chunk'lar halinde oku ve gönder
            with wave.open(INPUT_AUDIO_FILE, 'rb') as wf:
                while True:
                    data = wf.readframes(CHUNK_SIZE // 2) # 2 bytes per frame (16-bit)
                    if not data:
                        break # Dosya bitti
                    
                    await websocket.send(data)
                    
                    # Sunucudan cevap bekle (non-blocking)
                    try:
                        response_json = await asyncio.wait_for(websocket.recv(), timeout=0.01)
                        response = json.loads(response_json)
                        
                        if response.get("type") == "partial" and response.get("text"):
                            print(f"Kısmi Transkript: {response['text']}", end='\r')
                        
                        if response.get("type") == "final" and response.get("text"):
                            final_transcript = response['text']
                            print(f"\nNİHAİ TRANSKRİPT: {final_transcript}")
                            # Nihai sonucu alınca bu dosyayı stream etmeyi durdurabiliriz
                            # (Normalde VAD burada devreye girer, biz dosya sonuyla tetikliyoruz)
                            
                    except asyncio.TimeoutError:
                        pass # Cevap gelmedi, stream etmeye devam et
            
            # Dosya bittiğinde, Vosk'a "bitti" demek için boş bir chunk gönder
            # ve son nihai sonucu al
            await websocket.send(b'{"eof" : 1}')
            response_json = await websocket.recv()
            response = json.loads(response_json)
            if response.get("type") == "final" and response.get("text"):
                final_transcript = response['text']
                print(f"\nNİHAİ TRANSKRİPT (EOF): {final_transcript}")

            if not final_transcript:
                print("HATA: Sunucudan nihai transkript alınamadı.")
                return

    except Exception as e:
        print(f"HATA: WebSocket akışı sırasında hata: {e}")
        return

    # --- 2. Adım: Intent (LLM Analizi) ---
    print(f"\n--- 2. Adım: Intent Analizi (LLM) ---")
    print(f"Gönderilen Metin: '{final_transcript}'")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SERVER_API_URL}/get_intent",
                json={"text": final_transcript},
                timeout=30
            )
            response.raise_for_status()
            intent_json = response.json()
            print(f"Alınan Intent: {json.dumps(intent_json, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"HATA: Intent API çağrısı başarısız: {e}")
        return

    # --- 3. Adım: Cevap Cümlesi Oluşturma ve TTS ---
    print("\n--- 3. Adım: Cevap Sentezleme (TTS) ---")
    try:
        poliklinik = intent_json.get('poliklinik')
        sebep = intent_json.get('sebep_ozeti')

        if not poliklinik or poliklinik.lower() == "belirsiz":
            response_text = "Üzgünüm, şikayetinizi tam olarak anlayamadım. Lütfen daha detaylı anlatır mısınız?"
        else:
            response_text = f"Anladım. '{sebep}' şikayetiniz için sizi {poliklinik} polikliniğine yönlendiriyorum."
        
        print(f"Oluşturulan Cevap Cümlesi: '{response_text}'")

        # TTS API'sini çağır
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{SERVER_API_URL}/synthesize",
                json={"text": response_text},
                timeout=30
            )
            response.raise_for_status() # Hata varsa fırlat
            
            # Sesi dosyaya kaydet
            os.makedirs("tests", exist_ok=True)
            with open(OUTPUT_AUDIO_FILE, 'wb') as f:
                f.write(response.content)
            
            print(f"BAŞARILI: Cevap sesi '{OUTPUT_AUDIO_FILE}' olarak kaydedildi.")

            # Sesi Çal (Linux/Mac)
            try:
                print("Ses dosyası oynatılıyor...")
                subprocess.run(["xdg-open", OUTPUT_AUDIO_FILE], check=True) # Linux
                # subprocess.run(["open", OUTPUT_AUDIO_FILE], check=True) # MacOS
            except Exception:
                print(f"Sesi otomatik oynatılamadı. Lütfen '{OUTPUT_AUDIO_FILE}' dosyasını manuel açın.")

    except Exception as e:
        print(f"HATA: TTS adımı başarısız: {e}")
        return

if __name__ == "__main__":
    try:
        asyncio.run(run_realtime_flow())
    except KeyboardInterrupt:
        print("\nTest durduruldu.")
