@echo off
chcp 65001 >nul
setlocal
set "PY=C:\Users\38042\AppData\Local\Python\bin\python.exe"

REM 依赖自检
"%PY%" -c "import PySide6, qfluentwidgets, edge_tts" 2>nul || (
    echo [缺失依赖] 请先安装：
    echo %PY% -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6 PySide6-Fluent-Widgets edge-tts
    pause
    exit /b 1
)

cd /d "%~dp0"
"%PY%" main.py
endlocal
