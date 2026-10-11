#!/usr/bin/env python3
"""Clouvia Router CLI — daftar akun, klaim kredit gratis, panen API key, uji model.

  python clouvia.py harvest 5 --proxy --claim      # 5 akun + klaim 5M token
  python clouvia.py list                            # daftar akun + balance
  python clouvia.py test                            # uji semua key (chat)
  python clouvia.py claim --key clv_live_xxx        # klaim kredit akun yang ada
  python clouvia.py models --key clv_live_xxx       # daftar model + harga

Jalan di Linux/macOS/Windows. Di Linux headless tambahkan `xvfb-run -a`.
"""
import argparse
import asyncio
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from src import engine

ACCOUNTS = ROOT / "accounts.txt"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def log(m):
    print(f"[{time.strftime('%H:%M:%S', time.gmtime())}] {m}", flush=True)


def _req(url, key, body=None):
    r = urllib.request.Request(
        url, data=(json.dumps(body).encode() if body is not None else None),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": UA, "Accept": "application/json"},
        method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(r, timeout=90) as x:
            return x.status, x.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return 0, str(e)[:150]


def load_proxies(path=None):
    f = Path(path or str(ROOT / "proxies.txt"))
    if not f.exists():
        return []
    out = []
    for ln in f.read_text().splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = ln.split(":")
        out.append(f"http://{p[2]}:{p[3]}@{p[0]}:{p[1]}"
                   if (len(p) == 4 and not ln.startswith("http")) else ln)
    return out


def load_accounts():
    out = []
    if ACCOUNTS.exists():
        for ln in ACCOUNTS.read_text().splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                p = ln.split(":", 2)
                if len(p) == 3:
                    out.append({"email": p[0], "password": p[1], "key": p[2]})
    return out


# ---------- harvest ----------

async def harvest(n, proxies, tries, delay, do_claim):
    seen = {a["email"] for a in load_accounts()}
    log(f"target {n} akun | {len(proxies)} proxy | {tries} coba/akun | claim={do_claim}")
    ok = 0
    i = 0
    while ok < n and i < n * tries + 5:
        i += 1
        px = random.choice(proxies) if proxies else None
        log(f"── akun {ok + 1}/{n} (percobaan {i})" +
            (f" via {px.split('@')[-1]}" if px else " direct"))
        try:
            acc = await engine.create_account(log_fn=log, proxy=px, do_claim=do_claim)
        except Exception as e:
            log(f"  exception: {str(e)[:120]}")
            acc = None
        if acc and acc.get("email") and not acc.get("error"):
            if acc["email"] in seen:
                continue
            with ACCOUNTS.open("a") as f:
                f.write(f"{acc['email']}:{acc['password']}:{acc['apikey']}\n")
            seen.add(acc["email"])
            ok += 1
            log(f"✓ {acc['email']}  key={acc['apikey'][:24]}...")
            good, msg = engine.test_api_key(acc["apikey"])
            log(("  ✓ key: " + str(msg)[:70]) if good else ("  ! key: " + str(msg)[:70]))
        await asyncio.sleep(random.randint(delay, delay + 10))
    log(f"SELESAI: {ok} akun baru. Total: {len(load_accounts())}")


# ---------- list ----------

def cmd_list():
    accs = load_accounts()
    if not accs:
        print("belum ada akun")
        return
    print(f"{len(accs)} akun:")
    for a in accs:
        # balance & status key lewat /v1/models (yang menerima Bearer key)
        s, b = _req(f"{engine.BASE}/v1/models", a["key"])
        status = "AKTIF" if s == 200 else f"HTTP{s}"
        print(f"  {a['email']:<42} {status:<7} {a['key'][:30]}...")


# ---------- test ----------

def cmd_test():
    accs = load_accounts()
    if not accs:
        print("belum ada akun")
        return
    for a in accs:
        s, b = _req(f"{engine.BASE}/v1/chat/completions", a["key"],
                    {"model": "coding-high",
                     "messages": [{"role": "user", "content": "Reply exactly: OK"}],
                     "max_tokens": 10})
        if s == 200:
            try:
                out = json.loads(b)["choices"][0]["message"]["content"][:40]
            except Exception:
                out = b[:40]
            print(f"  VALID  {a['email']:<40} -> {out}")
        else:
            print(f"  GAGAL  {a['email']:<40} {s} {b[:80]}")


# ---------- claim / models ----------

def cmd_claim(a):
    target = None
    for x in load_accounts():
        if (a.key and x["key"] == a.key) or (a.email and x["email"] == a.email):
            target = x
            break
    if not target:
        print("akun tidak ditemukan di accounts.txt (pakai --key atau --email)")
        return
    ok = asyncio.run(engine.claim_credit(target["email"], target["password"], log_fn=log))
    print("klaim:", ok)


def cmd_models(a):
    key = a.key or (load_accounts()[0]["key"] if load_accounts() else None)
    if not key:
        print("butuh --key")
        return
    s, b = _req(f"{engine.BASE}/v1/models", key)
    if s != 200:
        print(f"HTTP {s}: {b[:200]}")
        return
    d = json.loads(b).get("data", [])
    print(f"{len(d)} model:")
    for m in d[:60]:
        p = m.get("pricing") or {}
        print(f"  {m.get('id'):<34} in={p.get('input_per_million','?')} out={p.get('output_per_million','?')}")


# ---------- main ----------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="clouvia", description="Clouvia Router suite")
    sub = ap.add_subparsers(dest="cmd", required=True)

    h = sub.add_parser("harvest", help="daftar akun + klaim kredit + panen API key")
    h.add_argument("n", nargs="?", type=int, default=1)
    h.add_argument("--proxy", action="store_true")
    h.add_argument("--proxy-file", default=None)
    h.add_argument("--tries", type=int, default=3)
    h.add_argument("--delay", type=int, default=30)
    h.add_argument("--claim", action="store_true", default=True,
                   help="klaim kredit gratis (default aktif)")

    sub.add_parser("list", help="daftar akun + balance")
    sub.add_parser("test", help="uji semua key (chat)")

    c = sub.add_parser("claim", help="klaim kredit akun yang sudah ada")
    c.add_argument("--key", default=None)
    c.add_argument("--email", default=None)

    m = sub.add_parser("models", help="daftar model + harga")
    m.add_argument("--key", default=None)

    a = ap.parse_args()
    if a.cmd == "harvest":
        asyncio.run(harvest(a.n, load_proxies(a.proxy_file) if a.proxy else [],
                            a.tries, a.delay, a.claim))
    elif a.cmd == "list":
        cmd_list()
    elif a.cmd == "test":
        cmd_test()
    elif a.cmd == "claim":
        cmd_claim(a)
    elif a.cmd == "models":
        cmd_models(a)
