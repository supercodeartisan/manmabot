Supply practice (independent drop loop)
=======================================

Launch: Tool_Supply_Practice.bat
  Uses VBS ShellExecute runas (Windows PowerShell 5.1 has no Start-Process -LiteralPath).
  Direct python entry also self-elevates via Tools/supply/elevate_supply_practice.py.

Uses Engine modules:
  inventory_listen, uidialog_listen, travel hops, ActionExecutor, Interception

Quantity prompt: Tools/supply/confirm_popup (UIdialogmon-style popup text)
  After Shift-drop, a popup whose message contains Esc+Enter = qty notice.
  Then type digits+Enter via Engine Interception KeyboardController
  (same capture as Shift-drag / Ctrl+I). Do not spawn enter_chat_cli for qty —
  a second Interception context was returning EC_E_TEXT (chars=0).

Grid pixels: Engine/data/supply/inventory_grid.json
  (scaled to live client via 4:3 content crop)

Registry: UIDLG_WIN_AmountSelector added for quantity popup.
