@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   构建「超星作业提取」主程序 + 安装包
echo ============================================
echo.

rem 必须用带 tkinter 的解释器；msys 的 python 才有 tkinter
set "PY=C:\msys64\mingw64\bin\python.exe"
if not exist "%PY%" (
  echo [错误] 找不到 %PY%
  echo        请安装 MSYS2 的 mingw64 环境，或修改本脚本里的 PY 路径。
  pause
  exit /b 1
)

if not exist ".build-venv\bin\python.exe" (
  echo [1/4] 创建构建环境...
  "%PY%" -m venv .build-venv
)
if not exist ".build-venv\bin\python.exe" (
  echo [错误] 创建虚拟环境失败
  pause
  exit /b 1
)

echo [2/4] 安装依赖（清华镜像）...
".build-venv\bin\python.exe" -m pip install -q --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple requests beautifulsoup4 pyinstaller
if errorlevel 1 (
  echo [错误] 依赖安装失败
  pause
  exit /b 1
)

echo [3/4] 打包主程序...
".build-venv\bin\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "超星作业提取" --icon "assets\app.ico" --add-data "assets;assets" ^
  --distpath dist --workpath build-tk app.py
if errorlevel 1 (
  echo [错误] 主程序打包失败
  pause
  exit /b 1
)
copy /y "dist\超星作业提取.exe" "超星作业提取.exe" >nul

echo [4/4] 打包安装程序...
".build-venv\bin\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "Windows-Setup" --icon "assets\app.ico" ^
  --add-data "超星作业提取.exe;payload" --add-data "README.md;payload" --add-data "LICENSE;payload" ^
  --hidden-import cx_eula --distpath dist-setup --workpath build-setup installer.py
if errorlevel 1 (
  echo [错误] 安装程序打包失败
  pause
  exit /b 1
)
copy /y "dist-setup\Windows-Setup.exe" "Windows-Setup.exe" >nul

echo.
echo ============================================
echo   完成：
echo     免安装版：超星作业提取.exe
echo     安装包　：Windows-Setup.exe
echo ============================================
pause
