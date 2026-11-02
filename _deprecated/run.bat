@echo off
cd /d %~dp0

rem 使用全局 Python 3.14.7（路径可按实际安装位置调整）
set PY=C:\Users\38042\AppData\Local\Python\bin\python.exe

if not exist "%PY%" (
    echo 未找到全局 Python 3.14.7：%PY%
    echo 请修改 run.bat 中的 PY 变量为你的 python.exe 路径。
    pause
    exit /b 1
)

"%PY%" -c "import PySide6, edge_tts" 2>nul
if errorlevel 1 (
    echo 缺少依赖 PySide6 / edge_tts，请先运行：
    echo "%PY%" -m pip install PySide6 edge-tts
    pause
    exit /b 1
)

"%PY%" main.py
pause
