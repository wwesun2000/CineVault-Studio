@echo off
REM CineVault Studio — One-Click Windows Standalone Executable (.exe) Builder
echo [CineVault Studio] Building Windows standalone executable via PyInstaller...
python -m PyInstaller --noconfirm --onefile --windowed ^
  --name "CineVaultStudio" ^
  --add-data "src/ui/index.html;src/ui" ^
  --add-data "AI_ENRICHMENT_GUIDE.md;." ^
  scripts/run_dev.py
echo [OK] Executable generated at dist\CineVaultStudio.exe
