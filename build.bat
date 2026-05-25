@echo off
echo === Stone of Fist — Build ===
echo.

echo [1/2] Installing PyInstaller...
pip install pyinstaller --quiet
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

echo [2/2] Building StoneOfFist.exe...
pyinstaller --onefile --noconsole --name StoneOfFist ^
    --add-data "templates;templates" ^
    --add-data "data;data" ^
    main.py

if errorlevel 1 (
    echo.
    echo ERROR: Build failed. Check output above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Done!  dist\StoneOfFist.exe
echo ============================================
echo.
pause
