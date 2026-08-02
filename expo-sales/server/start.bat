@echo off
cd /d %~dp0
echo 启动展会样品销售服务： http://0.0.0.0:8010
echo 首次运行请先安装依赖： pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8010
pause
