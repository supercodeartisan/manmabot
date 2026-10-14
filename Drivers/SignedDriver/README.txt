SignedDriver (WinNotify / signeddrv.sys)
========================================

Microsoft-signed kernel memory driver used by Engine analysis DLLs
(realtime_monitor, print_state, inventory, hotbar, shop).

Files
  signeddrv.sys         driver binary
  load_signeddrv.ps1    install/start/stop/remove (Administrator)

Usage
  powershell -ExecutionPolicy Bypass -File load_signeddrv.ps1 -Action start
  powershell -ExecutionPolicy Bypass -File load_signeddrv.ps1 -Action status
  powershell -ExecutionPolicy Bypass -File load_signeddrv.ps1 -Action stop

Or from product root: Driver_Start_SignedDriver.bat

Bot Start also launches this when the process is elevated.
