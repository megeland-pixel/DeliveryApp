@echo off
title Update and Restart Delivery App Server

echo ================================================
echo  Pulling latest from GitHub...
echo ================================================
cd /d "%~dp0"
git pull origin master
if %errorlevel% neq 0 (
    echo ERROR: git pull failed!
    pause
    exit /b 1
)

echo.
echo ================================================
echo  Restarting Delivery App Service...
echo ================================================
"C:\Program Files\nssm-2.24\win64\nssm.exe" restart DeliveryApp

echo.
echo Done!
timeout /t 3
