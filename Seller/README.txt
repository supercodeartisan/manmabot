ZF — Seller bundle (tool + SellerData)
======================================

This folder is SELLER-ONLY. Never put it in the customer zip.

Contents
--------
  Seller_License_Tool.bat   Launch the license UI
  seller_license_gui.py     UI script
  SellerData\               Keys, vault, license.db, artifacts
  README.txt                This file

Backup
------
Copy the whole Seller\ folder to a safe drive.
Losing SellerData means you cannot issue the same CEK / signing continuity.

Daily use
---------
1. Double-click Seller_License_Tool.bat
2. Create: enter Account/username → Create license key → send key + app zip
3. Fulfill: select customer activation_request.json → send response JSON only
4. Reset: for PC change; Export CSV for ledger

Customer must NEVER receive this folder.
