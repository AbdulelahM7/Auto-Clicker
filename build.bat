@echo off
REM Builds: dist\AutoClicker\ (app folder), dist-portable\AutoClicker-portable.exe,
REM and, if Inno Setup 6 is installed, dist-installer\AutoClicker-Setup-<version>.exe
setlocal
cd /d "%~dp0"

for /f "delims=" %%v in ('py -c "import autoclicker; print(autoclicker.__version__)"') do set VERSION=%%v
if "%VERSION%"=="" set VERSION=1.0.1
echo Building Auto Clicker v%VERSION%...

echo [1/4] Installing dependencies...
py -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :fail

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist dist-portable rmdir /s /q dist-portable
if exist build-portable rmdir /s /q build-portable

echo [2/4] Building app folder (used by the installer)...
py -m PyInstaller --noconfirm --clean --windowed --name AutoClicker --icon assets\icon.ico --add-data "assets;assets" --collect-all customtkinter --collect-all pystray --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 auto_clicker.py
if errorlevel 1 goto :fail

echo [3/4] Building portable single-file exe...
py -m PyInstaller --noconfirm --clean --onefile --windowed --name AutoClicker-portable --icon assets\icon.ico --add-data "assets;assets" --collect-all customtkinter --collect-all pystray --hidden-import pynput.keyboard._win32 --hidden-import pynput.mouse._win32 --distpath dist-portable --workpath build-portable auto_clicker.py
if errorlevel 1 goto :fail

echo [4/4] Building installer...
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" goto :noinno
"%ISCC%" /DAppVersion=%VERSION% installer\AutoClicker.iss
if errorlevel 1 goto :fail
echo.
echo Done:
echo   dist-installer\AutoClicker-Setup-%VERSION%.exe
echo   dist-portable\AutoClicker-portable.exe
goto :end

:noinno
echo.
echo Inno Setup 6 was not found, so the installer was skipped.
echo Install it from https://jrsoftware.org/isdl.php and run build.bat again.
echo Portable exe is ready: dist-portable\AutoClicker-portable.exe
goto :end

:fail
echo.
echo Build failed. See the messages above.
exit /b 1

:end
endlocal
