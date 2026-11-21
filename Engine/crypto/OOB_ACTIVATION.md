# Out-of-band activation (no HTTP server)

Seller and customer exchange **one request file** and **one response file**.
Crypto is the same as online activation (`ActivationService` + DeviceKey + ticket/envelope).

## Seller (preferred — UI)

Seller tool + vault live together under **`Seller/`** (never ship to customers).

- Double-click **`Seller\Seller_License_Tool.bat`** (or root `Seller_License_Tool.bat` shortcut)
- Data: **`Seller\SellerData\`** (keys, `license.db`, artifacts)

1. **Create license key** → copy key → send to customer with the zip  
2. When customer sends `activation_request.json` → **Select request file…** (Fulfill)  
3. Send the **response JSON** only  
4. PC change → select license → **Reset binding** → customer new request  

Backup the whole **`Seller\`** folder.

## Seller (fallback — cmd)

```bat
cd <product>
set PYTHONPATH=Engine
python -m crypto.seller_cli fulfill --request path\to\activation_request.json
```

Output: `Seller\SellerData\artifacts\response-<request_id>.json`  
Send **that file** to the customer.  
(`set MANMABOT_SELLER_DATA=%CD%\Seller\SellerData` if needed)

PC change later:

```bat
python -m crypto.seller_cli license reset <license_id> --reason pc-change
```

Then customer creates a **new** request.

## Customer (preferred — UI, no cmd)

1. Run `ZF.bat`
2. If not activated, a **License** window opens:
   - Enter license key → **Create request file**
   - **Open folder** / **Copy path** → send that file to the seller
   - **Select response file…** (or paste `MMB-RSP1.…`) → Apply
3. After success, ZF continues. Later runs are offline (no window).

## Customer (fallback — cmd)

```bat
cd <portable ManmabotV1>
set PYTHONPATH=Engine
python -m session.oob_activation request --license-key MMB-...
```

Send `UserData\license\activation_request.json` to the seller.

After the seller replies:

```bat
python -m session.oob_activation apply path\to\activation_response.json
```

This writes `UserData\license\ticket.json` + `envelope.json`. Later runs are offline.

## Rules

- Request TTL default **48h** (expired → new request).
- One license → one device until `license reset`.
- Response must never contain raw CEK / signing private keys.
- Pack/BUILD/`trusted_kids` verification is unchanged.

## DeviceKey (TPM → Soft)

First install prefers TPM. After a short retry, **Soft+DPAPI** is used when TPM
probe/create fails (transient / denied / unknown / absent), so customer laptops
are not blocked by `TPM transient error; Soft fallback forbidden`.

Full seller/customer handbook: **`LICENSE_HANDBOOK.md`** (same folder).
