@echo off
rem ============================================================
rem 智课罗盘 - 本地后端一键启动脚本
rem 双击运行即可。黑窗口要保持开着（关掉窗口 = 关掉后端）。
rem 小程序里再点一次登录就能连上。
rem ============================================================
cd /d D:\1111\default\backend

rem 检查虚拟环境是否存在
if not exist .venv\Scripts\python.exe (
    echo [错误] 找不到后端虚拟环境 .venv，请联系 ZCode 重建。
    pause
    exit /b 1
)

echo 正在启动智课罗盘后端 http://127.0.0.1:8000 ...
echo 启动后这个窗口不要关。想停掉后端：直接关掉本窗口即可。
echo.
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
pause
