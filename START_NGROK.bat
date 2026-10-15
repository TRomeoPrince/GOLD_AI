@echo off
title GOLD_AI ngrok
echo Starting GOLD_AI ngrok tunnel...
echo Public URL: https://grandpa-skier-sphere.ngrok-free.dev
echo Local server: http://127.0.0.1:8765
echo.
ngrok http --domain=grandpa-skier-sphere.ngrok-free.dev 8765
pause
