import requests
import json
import os
import subprocess

SERVER_URL = "http://127.0.0.1:8000"
INPUT_AUDIO_FILE = "data/samples/test_fixed3.wav" 
OUTPUT_AUDIO_FILE = "response.wav"

def run_full_flow():
    """
    Tüm STT -> LLM -> TTS akışını test eder.
    """
    
    print(f"Test akışı başlıyor: '{INPUT_AUDIO_FILE}' sunucuya gönderiliyor...")
    try:
        if not os.path.exists(INPUT_AUDIO_FILE):
            print(f"HATA: Test dosyası bulunamadı: {INPUT_AUDIO_FILE}")
            return

        with open(INPUT_AUDIO_FILE, 'rb') as f:
            files = {'file': (os.path.basename(INPUT_AUDIO_FILE), f, 'audio/wav')}
            response = requests.post(f"{SERVER_URL}/transcribe", files=files, timeout=45)
            response.raise_for_status()
        
        intent_json = response.json()
        print(f"\n[Adım 1 Tamamlandı] Analiz (LLM) Sonucu:\n{json.dumps(intent_json, indent=2, ensure_ascii=False)}")

    except requests.exceptions.RequestException as e:
        print(f"HATA: /transcribe endpoint'ine ulaşılamadı: {e}")
        return
    except json.JSONDecodeError:
        print(f"HATA: Sunucu JSON döndürmedi (Muhtemelen bir 500 hatası): {response.text}")
        return

    try:
        poliklinik = intent_json.get('poliklinik')
        sebep = intent_json.get('sebep_ozeti')

        if not poliklinik or poliklinik.lower() == "belirsiz":
            response_text = "Üzgünüm, şikayetinizi tam olarak anlayamadım. Lütfen daha detaylı anlatır mısınız?"
        else:
            response_text = f"Anladım. '{sebep}' şikayetiniz için sizi {poliklinik} polikliniğine yönlendiriyorum."
        
        print(f"\n[Adım 2 Tamamlandı] Oluşturulan Cevap Cümlesi:\n'{response_text}'")

    except Exception as e:
        print(f"HATA: JSON işlenirken hata oluştu: {e}")
        return

    print("\n[Adım 3 Başlıyor] Cevap cümlesi seslendiriliyor...")
    try:
        payload = {"text": response_text, "voice": "Kore"} # 'Kore' (varsayılan) veya 'Puck'
        response = requests.post(f"{SERVER_URL}/synthesize", json=payload, timeout=30)
        response.raise_for_status()

        with open(OUTPUT_AUDIO_FILE, 'wb') as f:
            f.write(response.content)
        
        print(f"\nBAŞARILI: Cevap sesi '{OUTPUT_AUDIO_FILE}' olarak kaydedildi.")
        
        try:
            print("Ses dosyası oynatılıyor...")
            subprocess.run(["xdg-open", OUTPUT_AUDIO_FILE], check=True) # Linux için
            # subprocess.run(["open", OUTPUT_AUDIO_FILE], check=True) # MacOS için
        except Exception:
            print(f"Sesi otomatik oynatılamadı. Lütfen '{OUTPUT_AUDIO_FILE}' dosyasını manuel açın.")

    except requests.exceptions.RequestException as e:
        print(f"HATA: /synthesize endpoint'ine ulaşılamadı: {e.response.text}")
        return

if __name__ == "__main__":
    run_full_flow()
