# Clouvia Router Suite

Factory akun **Clouvia Router** (gateway LLM Indonesia, 100+ model) otomatis —
daftar, verifikasi OTP, **klaim kredit gratis 5M token**, dan panen API key
`clv_live_…`. Jalan di **Windows / Linux / macOS**.

---

## Instalasi

**Windows**

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

**Linux / macOS**

```bash
bash setup.sh
```

## Pemakaian

```bash
# Linux/macOS (headless: xvfb-run)
xvfb-run -a .venv/bin/python clouvia.py harvest 5 --proxy

# Windows
clouvia.bat harvest 5 --proxy
```

| Command | Fungsi |
|---|---|
| `harvest [n] [--proxy] [--tries N] [--delay S]` | daftar `n` akun + klaim kredit + panen key |
| `list` | daftar akun + balance |
| `test` | uji semua key dengan chat |
| `claim --key clv_live_…` | klaim kredit akun yang sudah ada |
| `models [--key …]` | daftar model + harga |

Hasil tersimpan di `accounts.txt` format:

```
email:password:clv_live_api_key
```

## Alur (reverse-engineered)

```
1. inbox temp-mail (tempik)
2. GET /api/csrf                     -> cookie clv_csrf (wajib x-csrf-token)
3. Turnstile (sitekey 0x4AAAAAAEt-yhblOkoHFSQu)
   -> di-solve patchright (halaman minimal), token di-inject ke Camoufox
4. POST /api/auth/register
   {name,email,password,acceptTerms,turnstileToken}
   -> {"pending":true,"verificationRequired":true}
5. kode OTP 6-digit masuk email -> POST /api/auth/verify-email {email,otp}
   -> {"verified":true,"registered":true}
6. login -> POST /api/keys {name}
   -> 201, secret ada di **data.secret** (bukan data.key.key)
7. POST /api/credits/claim-starter  -> +5.000.000 token (starter gratis)
8. key clv_live_... siap dipakai di https://router.clouvia.id/v1
```

### Empat temuan yang menentukan

1. **Turnstile terikat domain.** Solver harus dibuka pada URL target
   (`router.clouvia.id/register`), bukan domain lain — kalau salah, token 0.
2. **CSRF wajib.** Cookie `clv_csrf` + header `x-csrf-token`; tanpa itu
   `CSRF_INVALID` (403).
3. **Secret key di `data.secret`**, sedangkan `data.key` hanya metadata
   (`keyPrefix`, `last4`) — kalau salah baca, key tidak dapat.
4. **Kredit gratis di `/api/credits/claim-starter`** (tombol "Claim 5M"),
   bukan lewat voucher. Tanpa klaim, akun baru balance 0 dan chat balas
   `402 Saldo token tidak mencukupi`.

## Pemakaian API

```bash
curl https://router.clouvia.id/v1/chat/completions \
  -H "Authorization: Bearer clv_live_..." \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0" \
  -d '{"model":"coding-high","messages":[{"role":"user","content":"halo"}]}'
```

> **User-Agent browser wajib** untuk panggilan dari script/library. Tanpa itu
> Cloudflare membalas `403 error code: 1010` (blokir client-signature, bukan
> masalah API key).

Model gratis/uji: `free-model`, `agnes-3.0-flash`, `agnes-2.5-flash`.
Model andalan: `coding-high` (thinking + agentic).

## Struktur

```
clouvia.py           CLI (harvest / list / test / claim / models)
src/engine.py        engine Camoufox: register + OTP + klaim + key
src/turnstile.py     solver Turnstile (patchright) + inject
ts_solve_cli.py      solver CLI (sitekey + URL sebagai argumen)
src/tempmail.py      klien temp-mail (API tempik)
src/config.py        loader config.toml
setup.sh / setup.ps1 instalasi (Linux-macOS / Windows)
clouvia.bat          wrapper Windows
```

## Pitfall

- **Jangan publish** `accounts.txt`, `proxies.txt`, `config.toml`, `data/`.
- **Rate limit per-IP** saat daftar banyak → pakai `--proxy` (rotasi).
- **Kredit 5M per akun**; kalau habis, chat balas `402`.
- Jalur kredit tambahan di konsol: **Daily Quests** (`/app/daily-quests`),
  **Voucher** (`/app/vouchers`), dan **link Telegram** (bonus).

## Kredit

- [Camoufox](https://github.com/daijro/camoufox) — Firefox anti-detect
- [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) — Chromium stealth (solver Turnstile)
- [tempik](https://github.com/hirotomasato/tempik) — layanan temp-mail
