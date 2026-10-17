ZF — folder layout
================

Top-level modules
  Engine\     Core app\ pipeline + session/settings/shop/hotbar/i18n/login
              (data\maps, data\cursors, analysis DLLs)
  UserData\   Operator settings written by the UI (defaults under UserData\defaults)
  Drivers\    Interception + SignedDriver (WinNotify / signeddrv.sys)
  UI\         Operator UI (package: ui)
  Docs\       Project documentation by topic
  Tools\      Data/calibration/experiment tools (not the live run loop)
  Research\   Research-only dumps (not runtime)
  Others\     Legacy duplicates, build leftovers, archived starters
  python\     Bundled interpreter (keep next to launchers)

Dependency direction
  UI -> Engine -> UserData / Drivers
  Tools may import Engine for experiments
  Engine must not import UI

Entry points (root surface)
  ZF.bat                           Main console
  ZF.exe                           Thin launcher -> run.py
  Tool_Hotbar_Inspector.bat
  Tool_Shopping_Practice.bat
  Tool_Shopping_Practice_Admin.bat
  Tool_Dungeon_Combat.bat
  Tool_Dungeon_Patrol_Editor.bat
  Tool_Screen_vs_Coordinate.bat
  Tool_Screen_vs_Coordinate_Admin.bat
  Driver_Install_Interception.bat
  Driver_Start_SignedDriver.bat    WinNotify / signeddrv.sys

First run
  1) Right-click Driver_Install_Interception.bat -> Run as administrator
  2) Start Lineage (LC.exe)
  3) Double-click ZF.bat (Administrator / UAC as prompted)
     Memory lamp also starts SignedDriver via Drivers\SignedDriver\
