@echo off
color 0A
echo === METIN2 OKEY BOTU - OTOMATIK DERLEYICI ===
echo [1/2] Eski onbellek, build ve dist klasorleri siliniyor...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q okey_asistani.spec 2>nul

echo [2/2] Tertemiz yeni EXE dosyasi olusturuluyor. Lutfen bekleyin...
python -m PyInstaller --clean --onefile --noconsole --hidden-import PIL --icon=NONE okey_asistani.py

echo === ISLEM TAMAMLANDI! ===
echo Yeni 'okey_asistani.exe' dosyaniz 'dist' klasorunun icinde hazir.
pause