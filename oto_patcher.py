import os
import sys
import time
import threading
import subprocess
import requests
import customtkinter as ctk

# --- SUNUCU AYARLARI (GİTHUB KULLANILABİLİR) ---
# Kendi GitHub deponuzu açtığınızda bu linkleri değiştireceksiniz.
# Şimdilik sistemin nasıl çalıştığını görmeniz için sahte ama hata vermeyen bir yapı kurduk.
GUNCEL_VERSION_URL = "https://raw.githubusercontent.com/kullanici/repo/main/version.txt"
GUNCEL_EXE_URL = "https://github.com/kullanici/repo/releases/download/v1.0/okey_asistani.exe"

YEREL_VERSION_DOSYASI = "version.txt"
ANA_PROGRAM_EXE = "okey_asistani.exe"

class PatcherGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Metin2 Okey Bot - Oto Patcher")
        self.geometry("500x250")
        self.resizable(False, False)
        
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")
        
        # Başlık
        self.baslik = ctk.CTkLabel(self, text="Yazılım Güncelleniyor...", font=("Segoe UI", 20, "bold"), text_color="#e8d9b2")
        self.baslik.pack(pady=(20, 10))
        
        # İlerleme Çubuğu
        self.progress = ctk.CTkProgressBar(self, width=400, height=20, corner_radius=10)
        self.progress.set(0)
        self.progress.pack(pady=10)
        
        # Durum Yazısı
        self.durum_lbl = ctk.CTkLabel(self, text="Sunucuya bağlanılıyor...", font=("Consolas", 12), text_color="#4CAF50")
        self.durum_lbl.pack(pady=5)
        
        # Güncellemeyi arka planda başlat
        threading.Thread(target=self.guncelleme_kontrol, daemon=True).start()
        
    def guncelleme_kontrol(self):
        try:
            self.guncelle_arayuz("Versiyon bilgisi kontrol ediliyor...", 0.1)
            time.sleep(1) # Animasyonu görebilmek için yapay bekleme
            
            # YEREL VERSİYONU OKU
            yerel_versiyon = "1.0"
            if os.path.exists(YEREL_VERSION_DOSYASI):
                with open(YEREL_VERSION_DOSYASI, "r") as f:
                    yerel_versiyon = f.read().strip()
            else:
                # Dosya yoksa oluştur
                with open(YEREL_VERSION_DOSYASI, "w") as f:
                    f.write(yerel_versiyon)
                    
            # SUNUCUDAN (GITHUB) YENİ VERSİYONU ÇEK
            try:
                # Sunucudan version.txt'yi çekiyoruz
                response = requests.get(GUNCEL_VERSION_URL, timeout=5)
                response.raise_for_status()
                sunucu_versiyon = response.text.strip()
            except:
                sunucu_versiyon = yerel_versiyon
                
            if sunucu_versiyon > yerel_versiyon:
                self.guncelle_arayuz(f"Yeni versiyon ({sunucu_versiyon}) bulundu. İndiriliyor...", 0.3)
                self.dosya_indir(GUNCEL_EXE_URL, ANA_PROGRAM_EXE)
                
                # Yeni versiyon numarasını kaydet
                with open(YEREL_VERSION_DOSYASI, "w") as f:
                    f.write(sunucu_versiyon)
            else:
                self.guncelle_arayuz("Sisteminiz güncel! Oyun başlatılıyor...", 1.0)
                time.sleep(1)
                
            self.oyunu_baslat()
            
        except Exception as e:
            self.guncelle_arayuz(f"Bağlantı hatası! Çevrimdışı başlatılıyor...", 1.0)
            time.sleep(2)
            self.oyunu_baslat()
            
    def dosya_indir(self, url, hedef_isim):
        """Gerçek dosya indirme ve ilerleme çubuğu senkronizasyonu"""
        try:
            response = requests.get(url, stream=True, timeout=10)
            response.raise_for_status()
            
            toplam_boyut = int(response.headers.get('content-length', 0))
            indirilen_boyut = 0
            
            with open(hedef_isim, 'wb') as f:
                for data in response.iter_content(chunk_size=8192):
                    if data:
                        f.write(data)
                        indirilen_boyut += len(data)
                        if toplam_boyut > 0:
                            yuzde = indirilen_boyut / toplam_boyut
                            yuzde_metin = int(yuzde * 100)
                            self.guncelle_arayuz(f"İndiriliyor... %{yuzde_metin}", yuzde)
        except Exception as e:
            self.guncelle_arayuz(f"İndirme hatası: {e}", 0.0)
            time.sleep(2)
            
    def guncelle_arayuz(self, metin, yuzde):
        self.durum_lbl.configure(text=metin)
        self.progress.set(yuzde)
        
    def oyunu_baslat(self):
        self.guncelle_arayuz("Okey Asistanı Başlatılıyor...", 1.0)
        time.sleep(0.5)
        
        # Ana exe dosyasını çalıştır ve Patcher'ı kapat
        if os.path.exists(ANA_PROGRAM_EXE):
            subprocess.Popen([ANA_PROGRAM_EXE])
        else:
            # Test aşamasındaysanız .py'yi çalıştırır
            if os.path.exists("okey_asistani.py"):
                subprocess.Popen([sys.executable, "okey_asistani.py"])
            else:
                print("Ana program bulunamadı!")
        
        self.destroy()

if __name__ == "__main__":
    # Gerekli kütüphane kontrolü (Sadece koddan çalıştırırken)
    try:
        import requests
    except ImportError:
        os.system("pip install requests")
        
    app = PatcherGUI()
    app.mainloop()