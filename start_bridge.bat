@echo off
set PROPY="C:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
set ARCGIS_BRIDGE_TOKEN=changeme
%PROPY% "%~dp0arcpy_bridge.py"
pause
