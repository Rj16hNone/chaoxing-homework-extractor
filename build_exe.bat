@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================
echo   打包「超星作业提取」桌面版 exe
echo ============================================
echo.

set "PYEXE="
if exist ".build-venv\Scripts\python.exe" set "PYEXE=.build-venv\Scripts\python.exe"
if exist ".build-venv\bin\python.exe" set "PYEXE=.build-venv\bin\python.exe"
if defined PYEXE goto build

echo [1/3] 检查 Python 和 tkinter...
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没找到 python。请先安装 Python 3.9+（python.org，安装时勾选 Add Python to PATH）。
  pause
  exit /b 1
)
python -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo [错误] 当前 Python 缺少 tkinter，无法打包图形界面。
  echo        请安装官方 Python（python.org）后重试；或者直接用现成的「超星作业提取.exe」。
  pause
  exit /b 1
)

echo [2/3] 创建独立构建环境（首次需要 1-2 分钟）...
python -m venv .build-venv
if errorlevel 1 (
  echo [错误] 创建虚拟环境失败
  pause
  exit /b 1
)
if exist ".build-venv\Scripts\python.exe" (set "PYEXE=.build-venv\Scripts\python.exe") else (set "PYEXE=.build-venv\bin\python.exe")
echo       安装依赖（优先用国内镜像，失败再走官方源）...
"%PYEXE%" -m pip install -q --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple requests beautifulsoup4 pyinstaller
if errorlevel 1 "%PYEXE%" -m pip install -q --disable-pip-version-check requests beautifulsoup4 pyinstaller
if errorlevel 1 (
  echo [错误] 依赖安装失败
  pause
  exit /b 1
)

:build
echo [3/4] 开始打包（约 20-60 秒）...
"%PYEXE%" -m PyInstaller --noconfirm --clean --onefile --noconsole ^
  --name "超星作业提取" ^
  --icon "assets\app.ico" --add-data "assets;assets" ^
  --distpath dist --workpath build-tk app.py
if errorlevel 1 (
  echo [错误] 打包失败
  pause
  exit /b 1
)

copy /y "dist\超星作业提取.exe" "超星作业提取.exe" >nul
echo.
echo [4/4] 生成发布 zip（只放 exe / 源码 / 图标，自动排除隐私文件）...
"%PYEXE%" make_zip.py
if errorlevel 1 (
  echo [错误] 生成 zip 失败
  pause
  exit /b 1
)
echo.
echo ============================================
echo   完成！直接双击「超星作业提取.exe」即可使用
echo   发布包：超星作业提取.zip（已排除 CookieKey / cookie / device）
echo ============================================
pause
