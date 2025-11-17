import os
import json
from vosk import Model, KaldiRecognizer, SetLogLevel

# Vosk loglarını kapat
SetLogLevel(-1)

class STTService:
    """
    Ses akışını (stream) gerçek zamanlı işleyen STT Servisi.
    Bu sınıf artık stateful (durum bilgili). 
    Her WebSocket bağlantısı için yeni bir 'STTService' örneği oluşturulmalıdır.
    """
    def __init__(self, sample_rate=16000):
        """
        Modeli ve tanıyıcıyı (recognizer) başlatır.
        """
        # Model yolu, bu dosyanın konumuna göre belirlenir
        service_dir = os.path.dirname(os.path.abspath(__file__))
        model_path = os.path.join(service_dir, "models", "vosk-model-small-tr-0.3")
        
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Vosk modeli bulunamadı: {model_path}")
            
        self.model = Model(model_path)
        self.recognizer = KaldiRecognizer(self.model, sample_rate)
        self.recognizer.SetWords(True) # Kısmi sonuçlar için kelimeleri de al
        
        print(f"[STTService] Yeni bir tanıyıcı başlatıldı (Rate: {sample_rate}).")

    def transcribe_chunk(self, chunk: bytes):
        """
        Bir ses 'chunk'ını (parçasını) işler.
        Konuşma devam ediyorsa kısmi sonuç, bittiyse nihai sonuç döner.

        Dönen JSON formatı:
        - {"type": "partial", "text": "boğazım ağrıyor..."}
        - {"type": "final", "text": "boğazım ağrıyor ve başım dönüyor"}
        """
        if self.recognizer.AcceptWaveform(chunk):
            # Konuşma durakladı veya bitti -> Nihai sonuç
            final_result = json.loads(self.recognizer.FinalResult())
            return {
                "type": "final",
                "text": final_result.get("text", "")
            }
        else:
            # Konuşma devam ediyor -> Kısmi sonuç
            partial_result = json.loads(self.recognizer.PartialResult())
            return {
                "type": "partial",
                "text": partial_result.get("partial", "")
            }

    def get_final_result(self):
        """
        Akış aniden kapandığında (örn. bağlantı koptu) 
        elimizdeki son veriyi nihai sonuca zorlar.
        """
        final_result = json.loads(self.recognizer.FinalResult())
        return {
            "type": "final",
            "text": final_result.get("text", "")
        }
