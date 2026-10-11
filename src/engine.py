"""Clouvia Router Engine — daftar akun + verifikasi OTP + panen API key.

Alur (reverse-engineered dari bundle /register):
  1. inbox tempik
  2. GET /api/csrf            -> cookie clv_csrf (wajib header x-csrf-token)
  3. Turnstile (render=explicit, sitekey 0x4AAAAAAEt-yhblOkoHFSQu)
     -> diselesaikan patchright, di-inject ke halaman
  4. POST /api/auth/register  {name,email,password,acceptTerms,referralCode?,turnstileToken}
  5. kode OTP 6-digit masuk email -> POST /api/auth/verify-email {email,otp}
  6. login -> ambil API key di konsol /app

Semua lewat halaman asli supaya cookie sesi + CSRF ikut.
"""
import asyncio
import json
import random
import re
import string
import time
from typing import Any, Dict, Optional, Tuple

from camoufox.async_api import AsyncCamoufox

from .tempmail import TempikClient
from .turnstile import solve as solve_turnstile, inject as inject_turnstile

BASE = "https://router.clouvia.id"
REGISTER = f"{BASE}/register"
LOGIN = f"{BASE}/login"
SITEKEY = "0x4AAAAAAEt-yhblOkoHFSQu"
_LAST_KEY_ID: list = []

GIVEN = ["Mason", "Leo", "Ryan", "Kai", "Evan", "Nolan", "Owen", "Adam",
         "Budi", "Andi", "Rizky", "Dewi", "Sari", "Putra"]
FAMILY = ["Chen", "Lin", "Wang", "Yang", "Liu", "Zhao", "Wu", "Xu",
          "Santoso", "Wijaya", "Pratama", "Nugroho"]


def gen_password() -> str:
    core = "".join(random.choices(string.ascii_letters + string.digits, k=11))
    return f"Clv!{core}9#"


def _parse_proxy(p: str) -> dict:
    from urllib.parse import urlparse
    if "://" not in p:
        p = "http://" + p
    u = urlparse(p)
    d = {"server": f"{u.scheme or 'http'}://{u.hostname}:{u.port}"}
    if u.username:
        d["username"] = u.username
    if u.password:
        d["password"] = u.password
    return d


def _proxy_exit_ip(proxy: str, timeout: int = 20) -> Optional[str]:
    import requests
    try:
        r = requests.get("https://api.ipify.org", proxies={"http": proxy, "https": proxy}, timeout=timeout)
        ip = r.text.strip()
        return ip if ip and len(ip) <= 45 else None
    except Exception:
        return None


async def _type(page, sel: str, text: str):
    """Isi field. `sel` boleh index ("idx:3") karena id React (":r0:") tidak
    valid sebagai selector CSS."""
    if sel.startswith("idx:"):
        n = int(sel.split(":")[1])
        await page.evaluate("""([n, val]) => {
            const el = [...document.querySelectorAll('input')][n];
            if (!el) return false;
            const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
            el.focus(); s.call(el, val);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            el.blur();
            return true;
        }""", [n, text])
        await page.wait_for_timeout(random.randint(120, 300))
        return
    await page.click(sel)
    await page.wait_for_timeout(random.randint(200, 500))
    for ch in text:
        await page.type(sel, ch, delay=random.randint(35, 100))
    await page.wait_for_timeout(random.randint(150, 350))


async def create_account(log_fn=print, proxy: str = None, do_claim: bool = True) -> Optional[Dict[str, Any]]:
    tc = TempikClient()
    email = tc.create_inbox()
    password = gen_password()
    name = f"{random.choice(GIVEN)} {random.choice(FAMILY)}"
    log_fn(f"[1/6] inbox: {email}")

    kw: Dict[str, Any] = {"headless": False, "humanize": True}
    if proxy:
        kw["proxy"] = _parse_proxy(proxy)
        kw["locale"] = "en-US"
        ip = await asyncio.to_thread(_proxy_exit_ip, proxy)
        if ip:
            kw["geoip"] = ip
            log_fn(f"    exit IP: {ip}")

    async with AsyncCamoufox(**kw) as browser:
        page = await browser.new_page()
        try:
            log_fn("[2/6] buka /register...")
            await page.goto(REGISTER, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(random.randint(2000, 3000))

            # CSRF cookie
            try:
                await page.evaluate("""async () => {
                    await fetch('/api/csrf', {method:'GET', credentials:'same-origin', cache:'no-store'});
                }""")
                await page.wait_for_timeout(800)
            except Exception:
                pass

            # OPTIMASI: solve token Turnstile untuk register DAN login sekaligus
            # (paralel). Token bisa dipakai kapan saja -> hemat ~19s/akun.
            t0 = time.time()
            tok_reg, tok_login = await asyncio.gather(
                asyncio.to_thread(solve_turnstile, SITEKEY, 120, False, REGISTER),
                asyncio.to_thread(solve_turnstile, SITEKEY, 120, False, LOGIN),
            )
            log_fn(f"[3/6] 2 token Turnstile (paralel) dalam {round(time.time()-t0,1)}s")

            # isi form (label-based; input tidak punya name)
            log_fn("[3/6] isi form...")
            inputs = await page.evaluate("""() => [...document.querySelectorAll('input')].map((i,idx)=>({idx, t:i.type, ph:i.placeholder}))""")
            texts = [i for i in inputs if i["t"] == "text"]
            emails = [i for i in inputs if i["t"] == "email"]
            pws = [i for i in inputs if i["t"] == "password"]
            ref = [i for i in texts if "rainmc" in (i.get("ph") or "").lower()]
            name_in = [i for i in texts if i not in ref]

            if name_in:
                await _type(page, f'idx:{name_in[0]["idx"]}', name)
            if emails:
                await _type(page, f'idx:{emails[0]["idx"]}', email)
            if pws:
                await _type(page, f'idx:{pws[0]["idx"]}', password)
            if len(pws) > 1:
                await _type(page, f'idx:{pws[1]["idx"]}', password)

            # checkbox terms
            await page.evaluate("""() => {
                const c = document.querySelector('input[type=checkbox]');
                if (c && !c.checked) c.click();
            }""")
            await page.wait_for_timeout(random.randint(600, 1200))

            # Turnstile: pakai token yang sudah di-solve di awal
            log_fn("[4/6] inject Turnstile...")
            tok = tok_reg
            if not tok:
                tok = solve_turnstile(SITEKEY, url=REGISTER) or ""
            if tok:
                inject_turnstile(page, tok)
                await page.wait_for_timeout(1500)
            log_fn(f"    token: {len(tok or '')} char")
            if not tok:
                return {"error": "no_turnstile", "proxy": proxy}

            # submit
            await page.wait_for_timeout(random.randint(2000, 4000))
            res = await page.evaluate("""async ([name, email, pwd, tok]) => {
                const c = document.cookie.split('; ').find(x=>x.startsWith('clv_csrf='));
                const csrf = c ? decodeURIComponent(c.slice(9)) : '';
                const r = await fetch('/api/auth/register', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {'Content-Type':'application/json','Accept':'application/json',
                              ...(csrf ? {'x-csrf-token': csrf} : {})},
                    body: JSON.stringify({name, email, password: pwd, acceptTerms: true,
                                          turnstileToken: tok})
                });
                return {status: r.status, body: (await r.text()).slice(0, 400)};
            }""", [name, email, password, tok])
            log_fn(f"    register: {res['status']} {res['body'][:160]}")
            if res["status"] not in (200, 201):
                return {"error": f"register_{res['status']}", "proxy": proxy,
                        "detail": res["body"][:200]}

            # OTP dari inbox
            log_fn("[5/6] tunggu OTP...")
            otp = await asyncio.to_thread(_read_otp, tc, email, 150)
            log_fn(f"    otp: {otp}")
            if not otp:
                return {"error": "no_otp", "proxy": proxy}

            vres = await page.evaluate("""async ([email, otp]) => {
                const c = document.cookie.split('; ').find(x=>x.startsWith('clv_csrf='));
                const csrf = c ? decodeURIComponent(c.slice(9)) : '';
                const r = await fetch('/api/auth/verify-email', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {'Content-Type':'application/json','Accept':'application/json',
                              ...(csrf ? {'x-csrf-token': csrf} : {})},
                    body: JSON.stringify({email, otp})
                });
                return {status: r.status, body: (await r.text()).slice(0, 300)};
            }""", [email, otp])
            log_fn(f"    verify: {vres['status']} {vres['body'][:140]}")
            if vres["status"] not in (200, 201):
                return {"error": f"verify_{vres['status']}", "proxy": proxy}

            # login -> konsol -> klaim kredit gratis + API key
            log_fn("[6/6] login, klaim kredit, ambil API key...")
            await page.goto(LOGIN, wait_until="domcontentloaded", timeout=40000)
            await page.wait_for_timeout(2000)
            lin = await page.evaluate("""() => [...document.querySelectorAll('input')].map((i,idx)=>({idx,t:i.type}))""")
            le = [i for i in lin if i["t"] == "email"]
            lp = [i for i in lin if i["t"] == "password"]
            if le and lp:
                await _type(page, f'idx:{le[0]["idx"]}', email)
                await _type(page, f'idx:{lp[0]["idx"]}', password)
                # turnstile login: pakai token yang sudah di-solve paralel
                lt = tok_login
                if not lt:
                    lt = solve_turnstile(SITEKEY, url=LOGIN) or ""
                if lt:
                    inject_turnstile(page, lt)
                    await page.wait_for_timeout(1000)
                await page.evaluate("""async ([email, pwd, tok]) => {
                    const c = document.cookie.split('; ').find(x=>x.startsWith('clv_csrf='));
                    const csrf = c ? decodeURIComponent(c.slice(9)) : '';
                    await fetch('/api/auth/login', {
                        method:'POST', credentials:'same-origin',
                        headers:{'Content-Type':'application/json',
                                 ...(csrf ? {'x-csrf-token': csrf} : {})},
                        body: JSON.stringify({email, password: pwd, turnstileToken: tok})
                    });
                }""", [email, password, lt])
                await page.wait_for_timeout(4000)

            await page.goto(f"{BASE}/app", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3000)

            # klaim kredit gratis: 5M token starter (+50M promo) per akun baru
            if do_claim:
              try:
                claim = await page.evaluate("""async () => {
                    const c = document.cookie.split('; ').find(x=>x.startsWith('clv_csrf='));
                    const csrf = c ? decodeURIComponent(c.slice(9)) : '';
                    const r = await fetch('/api/credits/claim-starter', {
                        method: 'POST', credentials: 'same-origin',
                        headers: {'Content-Type': 'application/json', 'Accept': 'application/json',
                                  ...(csrf ? {'x-csrf-token': csrf} : {})},
                        body: '{}'
                    });
                    return {s: r.status, b: (await r.text()).slice(0, 250)};
                }""")
                log_fn(f"    claim kredit: {claim['s']} {claim['b'][:150]}")
              except Exception as e:
                log_fn(f"    claim gagal: {str(e)[:100]}")

            key = await _harvest_key(page, log_fn)
            if not key:
                # akun SUDAH jadi & terverifikasi; simpan supaya tidak terbuang
                kid = _LAST_KEY_ID[-1] if _LAST_KEY_ID else ""
                log_fn(f"    akun jadi tapi key belum terbaca (key_id={kid})")
                return {"email": email, "password": password, "name": name,
                        "apikey": f"clv_live_PENDING_{kid}", "created_at": time.time()}

            return {"email": email, "password": password, "name": name,
                    "apikey": key, "created_at": time.time()}
        except Exception as e:
            log_fn(f"[!] error: {str(e)[:180]}")
            return {"error": "error", "proxy": proxy, "detail": str(e)[:150]}


def _read_otp(tc, email, timeout=150):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            for m in tc.get_messages(email):
                txt = re.sub(r"<[^>]+>", " ", (m.get("body") or "") + " " + (m.get("subject") or ""))
                mm = re.search(r"\b(\d{6})\b", txt)
                if mm:
                    return mm.group(1)
        except Exception:
            pass
        time.sleep(5)
    return None


async def _harvest_key(page, log_fn) -> Optional[str]:
    """Buat API key: POST /api/keys {name} -> data.key.key (plaintext)."""
    try:
        for body in ({"name": "router-prod"}, {"name": "default"}, {}):
            r = await page.evaluate("""async (body) => {
                const c = document.cookie.split('; ').find(x=>x.startsWith('clv_csrf='));
                const csrf = c ? decodeURIComponent(c.slice(9)) : '';
                const r = await fetch('/api/keys', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {'Content-Type': 'application/json', 'Accept': 'application/json',
                              ...(csrf ? {'x-csrf-token': csrf} : {})},
                    body: JSON.stringify(body)
                });
                return {s: r.status, b: (await r.text()).slice(0, 600)};
            }""", body)
            log_fn(f"    POST /api/keys -> {r['s']} BODY={r['b'][:500]}")
            if r["s"] in (200, 201):
                try:
                    d = json.loads(r["b"])
                    data = d.get("data") or {}
                    k = data.get("key") or {}
                    # plaintext ada di data.secret (bukan key.key)
                    val = (data.get("secret") or k.get("key") or k.get("plaintext")
                           or k.get("value") or data.get("plaintext"))
                    if val:
                        return val
                    log_fn(f"    (metadata saja, id={k.get('id')})")
                    _LAST_KEY_ID.append(k.get("id"))
                except Exception:
                    pass
        # fallback: GET /api/keys
        g = await page.evaluate("""async () => {
            const r = await fetch('/api/keys', {credentials:'same-origin', headers:{'Accept':'application/json'}});
            return {s: r.status, b: (await r.text()).slice(0, 800)};
        }""")
        m = re.search(r'(clv_live_[A-Za-z0-9_\-]{8,})', g["b"])
        return m.group(1) if m else None
    except Exception as e:
        log_fn(f"    key err: {str(e)[:100]}")
        return None


async def claim_credit(email: str, password: str, log_fn=print, proxy: str = None) -> dict:
    """Login ke akun yang sudah ada lalu klaim kredit starter."""
    kw: Dict[str, Any] = {"headless": False, "humanize": True}
    if proxy:
        kw["proxy"] = _parse_proxy(proxy)
        kw["locale"] = "en-US"
    async with AsyncCamoufox(**kw) as browser:
        page = await browser.new_page()
        try:
            await page.goto(LOGIN, wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(3500)
            await page.evaluate("""async () => { await fetch('/api/csrf',{credentials:'same-origin',cache:'no-store'}); }""")
            await page.wait_for_timeout(700)
            tok = solve_turnstile(SITEKEY, url=LOGIN) or ""
            log_fn(f"turnstile: {len(tok)} char")
            await page.evaluate("""async ([email, pwd, tok]) => {
                const c = document.cookie.split('; ').find(x=>x.startsWith('clv_csrf='));
                const csrf = c ? decodeURIComponent(c.slice(9)) : '';
                await fetch('/api/auth/login', {method:'POST', credentials:'same-origin',
                    headers:{'Content-Type':'application/json', ...(csrf?{'x-csrf-token':csrf}:{})},
                    body: JSON.stringify({email, password: pwd, turnstileToken: tok})});
            }""", [email, password, tok])
            await page.goto(f"{BASE}/app", wait_until="domcontentloaded", timeout=45000)
            await page.wait_for_timeout(4500)
            r = await page.evaluate("""async () => {
                const c = document.cookie.split('; ').find(x=>x.startsWith('clv_csrf='));
                const csrf = c ? decodeURIComponent(c.slice(9)) : '';
                const r = await fetch('/api/credits/claim-starter', {
                    method: 'POST', credentials: 'same-origin',
                    headers: {'Content-Type': 'application/json', 'Accept': 'application/json',
                              ...(csrf ? {'x-csrf-token': csrf} : {})}, body: '{}'});
                return {s: r.status, b: (await r.text()).slice(0, 300)};
            }""")
            log_fn(f"claim: {r['s']} {r['b'][:200]}")
            return r
        except Exception as e:
            log_fn(f"claim error: {str(e)[:150]}")
            return {"error": str(e)[:150]}


def test_api_key(api_key: str, base_url: str = BASE) -> Tuple[bool, str]:
    import requests
    try:
        r = requests.get(f"{base_url}/v1/models",
                         headers={"Authorization": f"Bearer {api_key}"}, timeout=25)
        if r.status_code == 200:
            d = r.json()
            ids = [m.get("id") for m in (d.get("data") or [])]
            return True, f"{len(ids)} model: {ids[:3]}"
        return False, f"HTTP {r.status_code}: {r.text[:100]}"
    except Exception as e:
        return False, str(e)[:120]
