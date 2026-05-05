@echo off
title Install Delivery App as Windows Service

set APP_DIR=E:\APPS\DeliveryApp
set NSSM="C:\Program Files\nssm-2.24\win64\nssm.exe"
set SERVICE=DeliveryApp

echo ================================================
echo  Installing %SERVICE% as a Windows service...
echo ================================================

%NSSM% install %SERVICE% "%APP_DIR%\run_app.bat"
%NSSM% set %SERVICE% AppDirectory "%APP_DIR%"
%NSSM% set %SERVICE% DisplayName "Delivery App"
%NSSM% set %SERVICE% Description "Driver delivery schedule web app"
%NSSM% set %SERVICE% Start SERVICE_AUTO_START

echo.
echo ================================================
echo  Starting %SERVICE%...
echo ================================================
%NSSM% start %SERVICE%

echo.
echo Done! Service installed at %APP_DIR%
pause
