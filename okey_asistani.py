import cv2
import numpy as np
from mss import mss
import time
import os
from typing import List, Dict, Any
import itertools
import pyautogui
import keyboard
import sys
import random
import glob
import shutil
import customtkinter as ctk
import threading
from PIL import Image

class OkeyAsistani:
    def __init__(self):
        # --- AYARLAR ---
        # EXE olarak çalıştırıldığında veya kısayoldan açıldığında şablon klasörünün yolunu kaybetmemesi için:
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        self.template_dir = os.path.join(base_dir, "sablonlar")
        self.match_threshold = 0.75 # Tarayıcı piksellenmeleri için hassasiyet düşürüldü
        
        self.colors = {'k': 'kirmizi', 'm': 'mavi', 's': 'sari'}
        self.templates: Dict[str, np.ndarray] = {}
        self.btn_templates: Dict[str, np.ndarray] = {} # Buton resimleri için
        self.hafiza = set() # Oyunda şu ana kadar görülen tüm kartları aklında tutar
        self.beklenen_kart_sayisi = 0
        self.kart_bekleme_sayaci = 0
        self.yeni_oyun_tiklama_sayisi = 0
        self.oyun_alani = None # Tarama alanını daraltmak için (ROI)
        self.tur_puani = 0 # Her turun skorunu arka planda matematiksel olarak hesaplar
        self.kazanilan_sandiklar = {"Bronz": 0, "Gümüş": 0, "Altın": 0}
        self.calisiyor = False # GUI üzerinden botu başlatıp/durdurmak için anahtar
        self.ui_callback = None # Arayüze anlık kart verisi göndermek için

    def yukle_sablonlar(self) -> bool:
        """sablonlar klasöründeki kart resimlerini belleğe yükler."""
        if not os.path.exists(self.template_dir):
            os.makedirs(self.template_dir)
            print(f"[UYARI] '{self.template_dir}' klasörü oluşturuldu. Lütfen içine kart resimlerini (örn: k1.png) ekleyin.")
            return False
        
        yuklenen_sayi = 0
        for c_kisa, c_uzun in self.colors.items():
            for i in range(1, 9):
                dosya_yolu = os.path.join(self.template_dir, f"{c_kisa}{i}.png")
                if os.path.exists(dosya_yolu):
                    self.templates[f"{c_uzun}_{i}"] = cv2.imread(dosya_yolu, cv2.IMREAD_COLOR)
                    yuklenen_sayi += 1
                    
        # Buton şablonlarını yükle
        for btn in ["cope_at", "set_oyna", "oyunu_bitir", "yeni_oyun"]:
            dosya_yolu = os.path.join(self.template_dir, f"{btn}.png")
            if os.path.exists(dosya_yolu):
                self.btn_templates[btn] = cv2.imread(dosya_yolu, cv2.IMREAD_COLOR)
            else:
                print(f"[BİLGİ] '{btn}.png' şablonu bulunamadı. Otomatik buton tıklaması çalışmayacak.")
                    
        print(f"[BİLGİ] {yuklenen_sayi} adet kart şablonu yüklendi.")
        return yuklenen_sayi > 0

    def kartlari_tespit_et(self, screen_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Ekrandaki şablonlarla eşleşen kartları bulur ve koordinatlarını döndürür."""
        bulunan_kartlar = []
        
        for isim, sablon in self.templates.items():
            res = cv2.matchTemplate(screen_bgr, sablon, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= self.match_threshold)
            
            for pt in zip(*loc[::-1]):
                renk, sayi = isim.split('_')
                skor = res[pt[1], pt[0]]
                bulunan_kartlar.append({"renk": renk, "sayi": int(sayi), "x": pt[0], "y": pt[1], "skor": float(skor)})
                
        # Çakışmaları önlemek için önce en yüksek (en emin olunan) eşleşmeleri öne al
        bulunan_kartlar.sort(key=lambda k: k['skor'], reverse=True)
        
        # PERFORMANS YAMASI: Ekranda max 5 kart olabilir, işlem yükünü azaltmak için sadece en iyi 50 eşleşmeyi filtrele.
        # Bu tek satır kod, binlerce piksellik yığılmanın botu saniyelerce dondurmasını engeller!
        bulunan_kartlar = bulunan_kartlar[:50]
        return self.kopyalari_filtrele(bulunan_kartlar)

    def kopyalari_filtrele(self, kartlar: List[Dict[str, Any]], min_mesafe: int = 40) -> List[Dict[str, Any]]:
        """Aynı kartın birden fazla kez okunmasını engeller."""
        benzersiz = []
        for k in kartlar:
            if not any(abs(k['x'] - b['x']) < min_mesafe and abs(k['y'] - b['y']) < min_mesafe for b in benzersiz):
                benzersiz.append(k)
        return benzersiz

    def buton_koordinati_bul(self, ekran_bgr: np.ndarray, buton_adi: str):
        """Ekrandaki butonu bulup merkez koordinatlarını (x, y) döndürür."""
        if buton_adi not in self.btn_templates:
            return None
        sablon = self.btn_templates[buton_adi]
        res = cv2.matchTemplate(ekran_bgr, sablon, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val >= 0.60: # Tarayıcı kaymalarına karşı buton hassasiyeti daha da esnetildi
            h, w = sablon.shape[:2]
            return (max_loc[0] + w // 2, max_loc[1] + h // 2) # Butonun tam orta noktası
        return None

    def tavsiye_ver(self, eldeki_kartlar: List[Dict[str, Any]], oyun_bitti_mi: bool = False) -> Dict[str, Any]:
        """Eldeki kartlara göre atılacak veya tutulacak kart tavsiyesi üretir."""
        
        # --- 0. ADIM: ÖN HESAPLAMALAR VE EV (BEKLENEN DEĞER) ANALİZİ ---
        oluler = self.hafiza - set((k['renk'], k['sayi']) for k in eldeki_kartlar)
        dusunce_log = ["\n--- 🧠 AI DÜŞÜNCE SÜRECİ ---"]

        kart_degerleri = []
        for kart in eldeki_kartlar:
            r = kart['renk']
            s = kart['sayi']
            
            olasi_setler = []
            # 1. AYNI RENK SERİLER
            for bas in range(max(1, s-2), min(7, s) + 1):
                if bas + 2 <= 8:
                    olasi_setler.append(([(r, bas), (r, bas+1), (r, bas+2)], bas * 10 + 40, "Aynı Renk Seri"))
                    
            # 2. PERLER
            diger_renkler = [renk for renk in self.colors.values() if renk != r]
            olasi_setler.append(([(r, s), (diger_renkler[0], s), (diger_renkler[1], s)], s * 10, "Per"))
            
            # 3. KARIŞIK RENK SERİLER
            renk_listesi = list(self.colors.values())
            for bas in range(max(1, s-2), min(7, s) + 1):
                if bas + 2 <= 8:
                    for c1 in renk_listesi:
                        for c2 in renk_listesi:
                            for c3 in renk_listesi:
                                if len(set([c1, c2, c3])) > 1:
                                    if (c1 == r and bas == s) or (c2 == r and bas+1 == s) or (c3 == r and bas+2 == s):
                                        olasi_setler.append(([(c1, bas), (c2, bas+1), (c3, bas+2)], bas * 10, "Karışık Seri"))

            max_ev = 0.0
            en_iyi_hedef = ""
            eldeki_tupler = set((k['renk'], k['sayi']) for k in eldeki_kartlar)
            
            for set_kartlari, set_puani, set_tipi in olasi_setler:
                mumkun = True
                eksik_kart = 0
                for sk in set_kartlari:
                    if sk not in eldeki_tupler:
                        eksik_kart += 1
                        if sk in oluler:
                            mumkun = False
                            break
                
                if mumkun:
                    if eksik_kart == 0: ev = set_puani * 10.0
                    elif eksik_kart == 1: ev = set_puani * 1.0
                    elif eksik_kart == 2: ev = set_puani * 0.1
                    
                    if ev > max_ev:
                        max_ev = ev
                        en_iyi_hedef = f"{set_tipi} ihtimali ({eksik_kart} kart eksik)"
                        
            if max_ev == 0:
                kart_degerleri.append({'kart': kart, 'puan': -1000.0 + (s * 0.01), 'aciklama': "Bütün kombinasyonları ölü (ÇÖP)"})
            else:
                kart_degerleri.append({'kart': kart, 'puan': max_ev + (s * 0.01), 'aciklama': f"EV: {max_ev:.1f} -> Beklenen: {en_iyi_hedef}"})

        kart_degerleri.sort(key=lambda x: x['puan'])
        en_gereksiz_dict = kart_degerleri[0] if kart_degerleri else None
        en_gereksiz = en_gereksiz_dict['kart'] if en_gereksiz_dict else None
        skoru = en_gereksiz_dict['puan'] if en_gereksiz_dict else 0
        
        for kd in kart_degerleri:
            k_isim = f"{kd['kart']['renk'].capitalize()} {kd['kart']['sayi']}"
            dusunce_log.append(f" > {k_isim} | {kd['aciklama']}")

        # --- 1. ADIM: SET KONTROLÜ (Skor Toplama) ---
        gecerli_setler = []
        if len(eldeki_kartlar) >= 3:
            # Eldeki kartlardan oluşabilecek tüm 3'lü olasılıkları (kombinasyonları) deniyoruz
            for combo in itertools.combinations(eldeki_kartlar, 3):
                renkler = [k['renk'] for k in combo]
                sayilar = sorted([k['sayi'] for k in combo])
                
                # Per Kuralı: 3'ü de FARKLI renk olacak ve sayıları aynı olacak (örn: K6, M6, S6)
                is_per = (len(set(renkler)) == 3) and (len(set(sayilar)) == 1)
                # Seri Kuralı: Ardışık olacak (Renk aynı veya farklı olabilir)
                is_seri = (sayilar[2] - sayilar[1] == 1) and (sayilar[1] - sayilar[0] == 1)
                is_ayni_renk = (len(set(renkler)) == 1)
                
                if is_per:
                    gecerli_setler.append({"combo": combo, "puan": sayilar[0] * 10, "tip": "PER"})
                elif is_seri:
                    puan = (sayilar[0] * 10) + 40 if is_ayni_renk else sayilar[0] * 10
                    tip = "AYNI RENK SERİ" if is_ayni_renk else "KARIŞIK RENK SERİ"
                    gecerli_setler.append({"combo": combo, "puan": puan, "tip": tip})
                    
        if gecerli_setler:
            # --- YAPAY ZEKA TIE-BREAKER (Eşitlik Bozucu) ---
            def set_kalite_skoru(s):
                kalan = [k for k in eldeki_kartlar if k not in s["combo"]]
                skor = float(s["puan"])
                if len(kalan) == 2:
                    k1, k2 = kalan[0], kalan[1]
                    if k1['renk'] == k2['renk'] and abs(k1['sayi'] - k2['sayi']) <= 2:
                        skor += (k1['sayi'] + k2['sayi']) * 0.01 
                    elif k1['sayi'] == k2['sayi']:
                        skor += k1['sayi'] * 0.01
                return skor
                
            en_iyi_set = max(gecerli_setler, key=set_kalite_skoru)
            
            # --- İLERİ SEVİYE YAPAY ZEKA: ALTIN SANDIK AÇGÖZLÜLÜĞÜ (Revize) ---
            oyna = True
            kalan_kart = 24 - len(self.hafiza)
            
            if not oyun_bitti_mi and kalan_kart > 5:
                # 1. KURAL: 30 Puan ve altındaki "Çöp Setleri" (örn: 1-2-3 vb.) normalde oynanmaz.
                # ANCAK: Çöpe atılacak kart 6, 7 veya 8 ise, bu değerli kartları feda etmek yerine çöp seti oynayıp eli boşaltıyoruz!
                if en_iyi_set["puan"] < 40:
                    if en_gereksiz and en_gereksiz['sayi'] >= 6:
                        dusunce_log.append(f" > [STRATEJİ] Çöpe değerli kart ({en_gereksiz['sayi']}) gitmemesi için {en_iyi_set['puan']} puanlık {en_iyi_set['tip']} MECBUREN OYNANIYOR.")
                    else:
                        oyna = False
                        dusunce_log.append(f" > [STRATEJİ] Puan çok düşük ({en_iyi_set['puan']}) olduğu için {en_iyi_set['tip']} İPTAL EDİLDİ.")
                    
                # 2. KURAL: 60 Puan ve altındaki vasat setleri SADECE Altın sandık ihtimalini bozuyorsa iptal et.
                elif en_iyi_set["tip"] != "AYNI RENK SERİ" and en_iyi_set["puan"] <= 60:
                    altin_bozuluyor = False
                    kullanilan_kartlar = en_iyi_set["combo"]
                    
                    # Oynayacağımız setin içindeki yüksek kartların eldeki diğer kartlarla "Aynı Renk Seri" potansiyeli var mı?
                    for k in kullanilan_kartlar:
                        if k['sayi'] >= 5: # 5, 6, 7 ve 8 numaraları altın potansiyelidir
                            eslesenler = [d for d in eldeki_kartlar if d['renk'] == k['renk'] and 1 <= abs(d['sayi'] - k['sayi']) <= 2 and d not in kullanilan_kartlar]
                            for b in eslesenler:
                                kucuk = min(k['sayi'], b['sayi'])
                                buyuk = max(k['sayi'], b['sayi'])
                                
                                # Eğer yan yanalar (Örn: 6 ve 7), altı veya üstü canlı mı?
                                if buyuk - kucuk == 1:
                                    canli_alt = kucuk > 1 and (k['renk'], kucuk - 1) not in oluler
                                    canli_ust = buyuk < 8 and (k['renk'], buyuk + 1) not in oluler
                                    if canli_alt or canli_ust:
                                        altin_bozuluyor = True
                                        break
                                # Eğer arada 1 boşluk varsa (Örn: 6 ve 8), ortadaki kart canlı mı?
                                elif buyuk - kucuk == 2:
                                    orta = kucuk + 1
                                    if (k['renk'], orta) not in oluler:
                                        altin_bozuluyor = True
                                        break
                        if altin_bozuluyor:
                            break
                    
                    # Eğer Altın Sandık serimiz bozuluyorsa ve elimizde atacak cidden çöp bir kart (1-5 arası) varsa iptal et!
                    if altin_bozuluyor and en_gereksiz:
                        if en_gereksiz not in kullanilan_kartlar and skoru < 150.0 and en_gereksiz['sayi'] < 6:
                            oyna = False
                            dusunce_log.append(f" > [STRATEJİ] Altın Sandık potansiyelini korumak için {en_iyi_set['puan']} puanlık {en_iyi_set['tip']} İPTAL EDİLDİ!")
                            
            if oyna:
                kart_isimleri = [f"{k['renk'].capitalize()} {k['sayi']}" for k in en_iyi_set["combo"]]
                dusunce_log.append(f" > [KARAR] {en_iyi_set['tip']} oynanıyor (+{en_iyi_set['puan']} Puan).")
                return {
                    "mesaj": f"[⭐⭐ SKOR ZAMANI! ⭐⭐] {en_iyi_set['tip']} OYNA: {' - '.join(kart_isimleri)} (+{en_iyi_set['puan']} Puan)",
                    "kartlar": en_iyi_set["combo"],
                    "aksiyon": "SET",
                    "puan": en_iyi_set["puan"],
                    "dusunce": "\n".join(dusunce_log)
                }

        # --- 1.5. ADIM: OYUN SONU (Deste Bitti) KONTROLÜ ---
        if oyun_bitti_mi or len(self.hafiza) >= 24:
            dusunce_log.append(" > [KARAR] Deste bitti ve oynanacak set kalmadı. Oyun bitiriliyor.")
            return {
                "mesaj": "[🚩 OYUN BİTTİ] Destede kart kalmadı ve set yok. Oyunu Bitir'e tıklanıyor!",
                "kartlar": [],
                "aksiyon": "BITIR",
                "dusunce": "\n".join(dusunce_log)
            }

        # --- 2. ADIM: KART ÇEKME BEKLEYİŞİ ---
        if len(eldeki_kartlar) < 5:
            return {"mesaj": f"Kart Çek bekleniyor... (Eldeki kart: {len(eldeki_kartlar)})", "kartlar": [], "aksiyon": None, "dusunce": ""}

        # --- 3. ADIM: ÇÖPE ATMA TAVSİYESİ ---
        sebep = "Geleceği yok / Ölü Kart" if skoru < 0 else f"EV Skoru: {skoru:.1f}"
        dusunce_log.append(f" > [KARAR] En değersiz kart olan {en_gereksiz['renk'].capitalize()} {en_gereksiz['sayi']} çöpe atılıyor.")
        return {
            "mesaj": f"[TAVSİYE] {en_gereksiz['renk'].upper()} {en_gereksiz['sayi']} numaralı kartı ÇÖPE AT! ({sebep})",
            "kartlar": [en_gereksiz],
            "aksiyon": "COPE",
            "dusunce": "\n".join(dusunce_log)
        }

    def asistan_baslat(self):
        print("=== METİN2 OKEY ASİSTANI BAŞLIYOR ===")
        if not self.yukle_sablonlar():
            print("Şablonlar bulunamadığı için asistan duraklatıldı. Lütfen resimleri ekleyip tekrar çalıştırın.")
            return

        # PyAutoGUI Güvenlik Ayarı (Fareyi ekranın en köşesine çekerseniz botu acil durdurur)
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.0 # PyAutoGUI gecikmesi tamamen sıfırlandı
        print("Ekran taranıyor... Çıkmak için CTRL+C yapabilirsiniz.\n")
        son_tavsiye = ""
        
        try:
            with mss() as sct:
                monitor = sct.monitors[1] # 1 numaralı (ana) monitörün tamamını seç
                while self.calisiyor:
                    # --- 🛑 ACİL DURDURMA (KILL-SWITCH) ---
                    if keyboard.is_pressed('esc'):
                        print("\n[BİLGİ] 🛑 ESC tuşuna basıldı! Acil durdurma aktif. Bot durduruluyor...")
                        self.calisiyor = False
                        break

                    # 1. Çift Görüş (Dual-Vision) Ekran Yakalama
                    # Butonları kaçırmamak için TÜM EKRANA, kartlar için OYUN ALANINA bakacağız.
                    tam_ekran_bgr = cv2.cvtColor(np.array(sct.grab(monitor)), cv2.COLOR_BGRA2BGR)
                    tarama_alani = self.oyun_alani if self.oyun_alani else monitor
                    
                    if self.oyun_alani:
                        oyun_ekran_bgr = cv2.cvtColor(np.array(sct.grab(tarama_alani)), cv2.COLOR_BGRA2BGR)
                    else:
                        oyun_ekran_bgr = tam_ekran_bgr
                    
                    # --- 1.5. YENİ OYUN KONTROLÜ (En Yüksek Öncelik) ---
                    # Ekranda Yeni Oyun butonu varsa, oyun bitmiş demektir. Kart taraması yapmadan direkt tıkla.
                    yeni_oyun_koordinat = self.buton_koordinati_bul(tam_ekran_bgr, "yeni_oyun")
                    if yeni_oyun_koordinat:
                        if len(self.hafiza) > 0:
                            print("\n[BİLGİ] Yeni oyun ekranı algılandı. Kart hafızası sıfırlandı ve oyuna başlanıyor.")
                            self.hafiza.clear()
                            self.beklenen_kart_sayisi = 0
                            self.kart_bekleme_sayaci = 0
                            self.yeni_oyun_tiklama_sayisi = 0
                            self.tur_puani = 0 # Her ihtimale karşı tur puanını sıfırla
                            
                        self.yeni_oyun_tiklama_sayisi += 1
                        if self.yeni_oyun_tiklama_sayisi > 3:
                            print("\n[🏆 GÖREV TAMAMLANDI] Biletler tükendi! (Tarayıcı uyarısı ekranda).")
                            print("=== 📊 OTURUM SONUCU ===")
                            print(f"🥇 Altın Sandık: {self.kazanilan_sandiklar['Altın']}")
                            print(f"🥈 Gümüş Sandık: {self.kazanilan_sandiklar['Gümüş']}")
                            print(f"🥉 Bronz Sandık: {self.kazanilan_sandiklar['Bronz']}")
                            print("Bot durduruluyor...\n")
                            self.calisiyor = False
                            break
                            
                        # Tıklamalara rastgele x,y ofseti (titreme) ve rastgele gidiş hızı eklendi
                        b_x = int(monitor["left"] + yeni_oyun_koordinat[0]) + random.randint(-15, 15)
                        b_y = int(monitor["top"] + yeni_oyun_koordinat[1]) + random.randint(-5, 5)
                        pyautogui.moveTo(b_x, b_y, duration=random.uniform(0.08, 0.18))
                        pyautogui.click()
                        print("[*] YENI_OYUN butonuna otomatik tıklandı!")
                        time.sleep(random.uniform(0.2, 0.4)) # Kartların dağıtılması için bekle
                        continue

                    # 2. Kartları Analiz Et
                    # Kartları arayüzde doğru sırayla göstermek için X koordinatına göre (soldan sağa) sıralıyoruz
                    kartlar = sorted(self.kartlari_tespit_et(oyun_ekran_bgr), key=lambda k: k['x'])
                    
                    if self.ui_callback:
                        self.ui_callback(kartlar)
                        
                    # --- ⚡ OTO-OPTİMİZASYON (BÖLGE KİLİTLEME) ---
                    # Ekranda kartları ilk bulduğunda, tarama alanını sadece o bölgeye daralt.
                    # Bu işlem, CPU'nun yaptığı 50 milyon piksel hesabını 5 milyona düşürür!
                    if self.oyun_alani is None and len(kartlar) >= 3:
                        min_x = min(k['x'] for k in kartlar)
                        max_x = max(k['x'] for k in kartlar)
                        min_y = min(k['y'] for k in kartlar)
                        max_y = max(k['y'] for k in kartlar)

                        pad_x, pad_top, pad_bot = 150, 100, 300
                        self.oyun_alani = {
                            "top": int(max(monitor["top"], monitor["top"] + min_y - pad_top)),
                            "left": int(max(monitor["left"], monitor["left"] + min_x - pad_x)),
                            "width": int(min(monitor["width"], (max_x - min_x) + pad_x * 2)),
                            "height": int(min(monitor["height"], (max_y - min_y) + pad_top + pad_bot))
                        }
                        print(f"\n[⚡ OTO-OPTİMİZASYON] Oyun alanı kilitlendi! İşlem yükü %80 azaltıldı.")
                        
                    # Deste Bitti Kilitlenmesini Önleme (Timeout Kontrolü)
                    if 0 < len(kartlar) < 5:
                        if len(kartlar) == self.beklenen_kart_sayisi:
                            self.kart_bekleme_sayaci += 1
                        else:
                            self.beklenen_kart_sayisi = len(kartlar)
                            self.kart_bekleme_sayaci = 0
                    else:
                        self.kart_bekleme_sayaci = 0
                        self.beklenen_kart_sayisi = len(kartlar)
                        
                    oyun_bitti_gorsel = self.buton_koordinati_bul(tam_ekran_bgr, "oyunu_bitir") is not None
                    # Deste bitti mi? (Görsel olarak veya 1 sn boyunca kart gelmediyse veya hafıza dolduysa)
                    oyun_bitti_mi = oyun_bitti_gorsel or (self.kart_bekleme_sayaci > 15) or (len(self.hafiza) >= 23)
                    
                    # Hafızayı Güncelle
                    for k in kartlar: self.hafiza.add((k['renk'], k['sayi']))

                    # 3. Karar Ver
                    karar = self.tavsiye_ver(kartlar, oyun_bitti_mi)
                    tavsiye_mesaji = karar["mesaj"]
                    
                    # 4. Sadece değişiklik varsa (veya önceki işlem başarısız olduysa) ekrana yazıp uygula
                    if tavsiye_mesaji != son_tavsiye:
                        if len(kartlar) >= 5:
                            tespit_edilenler = [f"{k['renk'].capitalize()} {k['sayi']}" for k in kartlar]
                            print(f"\n--- Görülen Kartlar: {', '.join(tespit_edilenler)} ---")
                            if karar.get("dusunce"):
                                print(karar["dusunce"])
                        print(f"\n> {time.strftime('%H:%M:%S')} | {tavsiye_mesaji}")
                        
                        islem_basarili = True # Aksiyonun başarıyla bitip bitmediğini takip edeceğiz
                        
                        # OTO-OYNA: Eğer bir aksiyon varsa farenin kontrolünü devral ve kartlara tıkla
                        if karar["aksiyon"]:
                            if karar["aksiyon"] in ["COPE", "SET"]:
                                for hedef in karar["kartlar"]:
                                    # Kartın şablondaki X,Y değerlerine ekranın genel ofsetini ve kartın tam merkezini (+25, +35 piksel) ekliyoruz
                                    hedef_x = int(tarama_alani["left"] + hedef["x"] + 25) + random.randint(-6, 6)
                                    hedef_y = int(tarama_alani["top"] + hedef["y"] + 35) + random.randint(-6, 6)
                                    pyautogui.moveTo(hedef_x, hedef_y, duration=random.uniform(0.05, 0.12))
                                    pyautogui.click()
                                    time.sleep(random.uniform(0.03, 0.08)) # Tıklamalar arası rastgele bekleme
                                    
                                time.sleep(random.uniform(0.05, 0.15)) # Kartların seçilip butonun aktifleşmesini bekle
                                
                                # BUTONLARI BULMAK İÇİN GÜNCEL EKRAN GÖRÜNTÜSÜ AL (Geçmişte arama yapmasını önler)
                                guncel_tam_ekran = cv2.cvtColor(np.array(sct.grab(monitor)), cv2.COLOR_BGRA2BGR)
                                
                                aranacak_buton = "cope_at" if karar["aksiyon"] == "COPE" else "set_oyna"
                                buton_koordinati = self.buton_koordinati_bul(guncel_tam_ekran, aranacak_buton)
                                
                                if buton_koordinati:
                                    b_x = int(monitor["left"] + buton_koordinati[0]) + random.randint(-10, 10)
                                    b_y = int(monitor["top"] + buton_koordinati[1]) + random.randint(-3, 3)
                                    pyautogui.moveTo(b_x, b_y, duration=random.uniform(0.08, 0.15))
                                    pyautogui.click()
                                    print(f"[*] {aranacak_buton.upper()} işlemine otomatik tıklandı!")
                                    
                                    # Başarılı bir Set oynadıysa botun puanını topla
                                    if karar["aksiyon"] == "SET":
                                        self.tur_puani += karar.get("puan", 0)
                                    time.sleep(random.uniform(0.05, 0.15))
                                else:
                                    islem_basarili = False # Buton ekrana gelmedi, başarısız
                                    
                            elif karar["aksiyon"] == "BITIR":
                                time.sleep(random.uniform(0.1, 0.2)) # UI animasyonu (butonun belirmesi) için anlık bekleme
                                guncel_tam_ekran = cv2.cvtColor(np.array(sct.grab(monitor)), cv2.COLOR_BGRA2BGR)
                                buton_koordinati = self.buton_koordinati_bul(guncel_tam_ekran, "oyunu_bitir")
                                
                                if buton_koordinati:
                                    b_x = int(monitor["left"] + buton_koordinati[0]) + random.randint(-10, 10)
                                    b_y = int(monitor["top"] + buton_koordinati[1]) + random.randint(-3, 3)
                                    pyautogui.moveTo(b_x, b_y, duration=random.uniform(0.08, 0.18))
                                    pyautogui.click()
                                    print(f"[*] OYUNU_BITIR işlemine otomatik tıklandı!")
                                    
                                    # Oyun bittiğinde arka planda hesaplanan skora göre kazanılan sandığı logla
                                    if self.tur_puani >= 400:
                                        self.kazanilan_sandiklar["Altın"] += 1
                                        sandik = "🥇 Altın"
                                    elif self.tur_puani >= 250:
                                        self.kazanilan_sandiklar["Gümüş"] += 1
                                        sandik = "🥈 Gümüş"
                                    else:
                                        self.kazanilan_sandiklar["Bronz"] += 1
                                        sandik = "🥉 Bronz"
                                    print(f"\n[🏁 TUR BİTTİ] Toplam Puan: {self.tur_puani} -> Kazanılan: {sandik} Sandık\n")
                                    
                                    time.sleep(random.uniform(0.15, 0.3)) # Animasyonu bekle
                                else:
                                    islem_basarili = False # Buton ekrana gelmedi, başarısız
                            
                        if islem_basarili:
                            son_tavsiye = tavsiye_mesaji
                        else:
                            son_tavsiye = "" # İşlem başarısız olduysa mesajı sıfırla, böylece döngüde tekrar dener!
                    
                    time.sleep(0.01) # Botun ekran tarama beklemesi neredeyse sıfırlandı
        except KeyboardInterrupt:
            print("\n[BİLGİ] Asistan kullanıcı tarafından kapatıldı.")

class TextRedirector:
    """Botun ürettiği yazıları Terminal yerine doğrudan Arayüze ve TXT dosyasına yansıtır."""
    def __init__(self, text_widget):
        self.text_widget = text_widget
        dosya_adi = f"okey_log_{time.strftime('%Y_%m_%d_%H%M%S')}.txt"
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        # Loglar için "Logs" klasörünü oluştur ve yolu ayarla
        log_dir = os.path.join(base_dir, "Logs")
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)
            
        log_path = os.path.join(log_dir, dosya_adi)
        self.log_file = open(log_path, "w", encoding="utf-8")
        
        # Eski kalıntıları temizle (Ana dizindeki eski logları toplayıp Logs klasörüne taşır)
        eski_loglar = glob.glob(os.path.join(base_dir, "okey_log*.txt"))
        for eski_log in eski_loglar:
            try:
                shutil.move(eski_log, os.path.join(log_dir, os.path.basename(eski_log)))
            except Exception:
                pass
        
        # Arayüz açıldığında dosyanın tam olarak nereye kaydedildiğini ekrana bas
        self.write(f"[BİLGİ] Canlı oturum kayıtları şu konuma kaydediliyor:\n-> {log_path}\n\n")
        
    def write(self, message):
        self.text_widget.insert("end", message)
        self.text_widget.see("end") # Her yeni yazıda otomatik en aşağıya kaydırır
        self.log_file.write(message)
        self.log_file.flush()
        
    def flush(self):
        self.log_file.flush()

class BotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Metin2 Okey Asistanı - V2.0 PRO")
        self.root.geometry("850x650")
        
        # ctk ayarları (Koyu Tema ve Yeşil Vurgular)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("green")

        # Üst Panel (Butonlar)
        ust_frame = ctk.CTkFrame(root, fg_color="transparent")
        ust_frame.pack(pady=20)
        
        self.baslat_btn = ctk.CTkButton(ust_frame, text="▶ B O T U   B A Ş L A T", fg_color="#2b5c3a", hover_color="#3b7d4f", font=("Segoe UI", 14, "bold"), width=250, height=45, corner_radius=8, command=self.baslat)
        self.baslat_btn.grid(row=0, column=0, padx=15)
        
        self.durdur_btn = ctk.CTkButton(ust_frame, text="⏹ D U R D U R (ESC)", fg_color="#7d3b3b", hover_color="#9d4b4b", font=("Segoe UI", 14, "bold"), width=250, height=45, corner_radius=8, command=self.durdur)
        self.durdur_btn.grid(row=0, column=1, padx=15)
        
        self.durum_lbl = ctk.CTkLabel(root, text="Durum: BEKLİYOR", text_color="#d4c8a9", font=("Segoe UI", 16, "bold"))
        self.durum_lbl.pack(pady=10)
        
        # Oyun Canlı Ekranı (Kartlar)
        self.kart_frame = ctk.CTkFrame(root, fg_color="transparent")
        self.kart_frame.pack(pady=5)
        
        self.kart_labelleri = []
        for i in range(5):
            lbl = ctk.CTkLabel(self.kart_frame, text="?", width=65, height=90, fg_color="#1e1e1e", corner_radius=8, font=("Segoe UI", 28, "bold"))
            lbl.grid(row=0, column=i, padx=8)
            self.kart_labelleri.append(lbl)
            
        # Canlı Skor ve Kalan Kart
        self.skor_lbl = ctk.CTkLabel(root, text="Skor: 0  |  Kalan Kart: 24", text_color="#d4af37", font=("Segoe UI", 16, "bold"))
        self.skor_lbl.pack(pady=5)
        
        # Alt Panel (Konsol)
        self.konsol = ctk.CTkTextbox(root, fg_color="#1e1e1e", text_color="#4CAF50", font=("Consolas", 12), corner_radius=10, wrap="word")
        self.konsol.pack(padx=25, pady=10, fill="both", expand=True)
        
        self.bot = OkeyAsistani()
        self.bot.ui_callback = self.update_cards_ui
        
        # Resimleri Önbelleğe Al
        self.kart_resimleri = {}
        self.load_ui_images()
        
        sys.stdout = TextRedirector(self.konsol) # Artık tüm print() mesajları bu ekrana düşecek!
        
    def load_ui_images(self):
        """Arayüzde gösterilecek kart resimlerini yükler."""
        renkler = {'kirmizi': 'k', 'mavi': 'm', 'sari': 's'}
        for c_uzun, c_kisa in renkler.items():
            for i in range(1, 9):
                path = os.path.join(self.bot.template_dir, f"{c_kisa}{i}.png")
                if os.path.exists(path):
                    img = Image.open(path)
                    # Kart boyutlarını GUI için optimize et (Küçült)
                    self.kart_resimleri[f"{c_uzun}_{i}"] = ctk.CTkImage(light_image=img, dark_image=img, size=(65, 90))

    def update_cards_ui(self, kartlar):
        # Tkinter thread-safe olmadığı için, botun yolladığı verileri güvenli şekilde ana ekrana (main thread) iter
        self.root.after(0, self._do_update_cards, kartlar)
        
    def _do_update_cards(self, kartlar):
        # 1. Kartları Çiz
        for i in range(5):
            if i < len(kartlar):
                k = kartlar[i]
                anahtar = f"{k['renk']}_{k['sayi']}"
                if anahtar in self.kart_resimleri:
                    self.kart_labelleri[i].configure(image=self.kart_resimleri[anahtar], text="")
                else:
                    self.kart_labelleri[i].configure(image="", text=f"{k['sayi']}")
            else:
                self.kart_labelleri[i].configure(image="", text="?")
                
        # 2. Skor ve Desteyi Güncelle
        kalan_kart = max(0, 24 - len(self.bot.hafiza))
        self.skor_lbl.configure(text=f"Skor: {self.bot.tur_puani}  |  Kalan Kart: {kalan_kart}")
        
    def baslat(self):
        if not self.bot.calisiyor:
            self.bot.calisiyor = True
            self.durum_lbl.configure(text="Durum: ÇALIŞIYOR (Oyun Alanı Taranıyor)", text_color="#4CAF50")
            # Arayüzün donmaması için botun sonsuz döngüsünü yan bir iş parçacığında (Thread) başlatıyoruz
            threading.Thread(target=self.run_bot, daemon=True).start()
            
    def run_bot(self):
        self.bot.asistan_baslat()
        self.durum_lbl.configure(text="Durum: DURDU", text_color="#f44336")
        self.bot.calisiyor = False
        
    def durdur(self):
        if self.bot.calisiyor:
            print("\n[BİLGİ] Kullanıcı tarafından durdurma isteği gönderildi...")
            self.bot.calisiyor = False

if __name__ == "__main__":
    root = ctk.CTk()
    app = BotGUI(root)
    root.mainloop()