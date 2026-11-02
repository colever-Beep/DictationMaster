@echo off
rem ============================================================
rem  听写助手打包脚本（PyInstaller onedir）
rem  用法：双击运行或在项目根目录执行 build.bat
rem  产物：dist\DictationMaster\DictationMaster.exe
rem ============================================================
setlocal
cd /d "%~dp0"

echo [1/3] 检查 PyInstaller ...
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo 未安装 PyInstaller，正在安装（使用清华镜像）...
    python -m pip install pyinstaller -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo 安装 PyInstaller 失败，请检查网络后重试。
        exit /b 1
    )
)

echo [2/3] 开始打包（可能需要几分钟）...
python -m PyInstaller app.spec --noconfirm
if errorlevel 1 (
    echo 打包失败，请查看上方报错信息。
    exit /b 1
)

echo [3/3] 自检 Qt 多媒体插件（缺失会导致打包后没有声音）...
set "FOUND=0"
if exist "dist\DictationMaster\_internal\PySide6\plugins\multimedia" set "FOUND=1"
if exist "dist\DictationMaster\PySide6\plugins\multimedia" set "FOUND=1"
if "%FOUND%"=="0" (
    echo [警告] 未找到 multimedia 插件目录！打包产物可能完全没有声音。
    echo        请检查 app.spec 中 collect_all("PySide6") 是否生效。
) else (
    echo 多媒体插件自检通过。
)

echo.
echo 打包完成：dist\DictationMaster\DictationMaster.exe
echo 整个 DictationMaster 文件夹即为发布产物，解压/复制到任意 Windows 机器即可运行。
endlocal
