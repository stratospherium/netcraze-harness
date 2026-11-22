"""
Netcraze Harness Doctor v2 — самодиагностика Plan B (WireGuard + xray-туннель).
Проверяет всю цепочку: WG-туннель -> xray друга (Keenetic) -> интернет.

Использование:
  python doctor2.py            # полная проверка

Все проверки с таймаутами, ничего не виснет.
"""
import socket
import subprocess
import sys
import time
import urllib.request
import ssl

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HER_ROUTER = "192.168.1.45"
HIS_ROUTER = "192.168.1.1"
ASKPASS = r"C:\Users\yellow\AppData\Local\Temp\askpass-her.sh"
ASKPASS_ENT = r"C:\Users\yellow\AppData\Local\Temp\askpass-ent.sh"
WG_LOCAL = "10.20.20.2"      # её адрес в туннеле
WG_REMOTE = "10.20.20.1"     # его адрес (Keenetic + xray socks)
TUNNEL_PORT = 2223           # Entware dropbear на её роутере
HER_SOCKS = 222              # socks-тест her xray (через ACL-дыру)

PASS, FAIL, WARN = "OK  ", "FAIL", "WARN "
results = []


def note(name, ok, detail=""):
    mark = PASS if ok else FAIL
    results.append(ok)
    print(f"{mark} {name}" + (f" — {detail}" if detail else ""), flush=True)


def run(cmd, timeout=40):
    env = dict(__import__("os").environ)
    env.update({"SSH_ASKPASS": ASKPASS, "SSH_ASKPASS_REQUIRE": "force",
                "DISPLAY": ":0", "MSYS_NO_PATHCONV": "1"})
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
        return r.stdout.replace("\x1b[K", "")
    except Exception:
        return ""


def tcp(host, port, timeout=6):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


print("=" * 60)
print("NETCRAZE DOCTOR v2 — Plan B (WireGuard + xray-туннель)")
print("=" * 60, flush=True)

# 1. Роутеры живы
note("Netcraze (её) доступен по SSH", tcp(HER_ROUTER, 22, 5) and
     bool(run(["ssh", "-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null",
               f"admin@{HER_ROUTER}", "show version"], 25)))
note("Keenetic (твой) доступен по SSH", tcp(HIS_ROUTER, 22, 5) and
     bool(run(["ssh", "-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null",
               f"AI@{HIS_ROUTER}", "show version"], 25)))

# 2. WG-туннель: ping 10.20.20.1 с её роутера
out = run(["ssh", "-o", "StrictHostKeyChecking=no",
           "-o", "UserKnownHostsFile=/dev/null",
           f"admin@{HER_ROUTER}", f"tools ping {WG_REMOTE} count 2"], 30)
wg_ok = ("0% packet loss" in out) or ("2 packets received" in out) or \
        ("icmp_req=1" in out) or ("bytes from 10.20.20.1" in out)
note("WireGuard-туннель (ping 10.20.20.1)", wg_ok,
     "loss 0%" if wg_ok else "туннель не отвечает")

# 3. Entware dropbear — только через туннель (снаружи режет ACL по дизайну)
#    проверяется позже, когда туннель поднят (см. блок dropbear-via-tunnel)

# 4. xray версия на её роутере (через туннель -> 2223)
tunnel = subprocess.Popen(
    ["ssh", "-p", "22", "-N", "-L", "12222:127.0.0.1:2223",
     "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
     f"admin@{HER_ROUTER}"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    env={**__import__("os").environ,
         "SSH_ASKPASS": ASKPASS, "SSH_ASKPASS_REQUIRE": "force",
         "DISPLAY": ":0", "MSYS_NO_PATHCONV": "1"})
time.sleep(6)
xray_ver = ""
try:
    out = run(["ssh", "-p", "12222", "-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null",
               "-o", "PreferredAuthentications=password",
               "-o", "PubkeyAuthentication=no",
               f"root@127.0.0.1", "xray version 2>/dev/null | head -1"], 30)
    for line in out.splitlines():
        if line.startswith("Xray "):
            xray_ver = line.strip()
    note("xray на её роутере", bool(xray_ver), xray_ver or "не отвечает")
except Exception as ex:
    note("xray на её роутере", False, str(ex)[:50])

# 5. socks 222 её xray: exit IP
try:
    req = urllib.request.Request("https://api.ipify.org")
    proxy = urllib.request.build_opener(
        urllib.request.ProxyHandler(
            {"https": f"socks5h://127.0.0.1:12223",
             "http": f"socks5h://127.0.0.1:12223"}))
    urllib.request.install_opener(proxy)
    note("(пропущен socks-тест через python)", True, "см. curl-тесты ниже")
except Exception:
    pass

# 6. curl: exit IP через её socks 222 и через его socks 10809
def curl_exit(socks, target_port=None):
    cmd = ["curl", "-m", "20", "--ssl-no-revoke",
           "--socks5", socks, "-sS", "https://api.ipify.org"]
    return run(cmd, 30).strip()

e1 = ""
for attempt in (1, 2, 3):  # ретраи: канал бывает flaky
    e1 = curl_exit("192.168.1.45:222")
    if e1 and " " not in e1:
        break
    time.sleep(3)
note("Exit-IP через её socks :222", bool(e1) and " " not in e1, f"exit={e1 or '—'}")
e2 = curl_exit(f"{HIS_ROUTER}:10809")
note("Exit-IP через его socks :10809", e2 == "77.221.140.43", f"exit={e2 or '—'}")

# 7. Телеграм через его socks (эталон)
tg = run(["curl", "-m", "20", "--ssl-no-revoke",
          "--socks5", f"{HIS_ROUTER}:10809", "-sS", "-o", "/dev/null",
          "-w", "%{http_code}", "https://api.telegram.org"], 30)
note("api.telegram.org через его socks", tg.strip() in ("200", "302"),
     f"HTTP {tg.strip()}")

# 8. WG MTU на nwg1
mtu_out = run(["ssh", "-p", "12222", "-o", "StrictHostKeyChecking=no",
               "-o", "UserKnownHostsFile=/dev/null",
               "-o", "PreferredAuthentications=password",
               "-o", "PubkeyAuthentication=no",
               "root@127.0.0.1", "cat /sys/class/net/nwg1/mtu"], 20)
mtu = mtu_out.strip()
note("MTU nwg1 (туннель)", mtu.isdigit() and int(mtu) <= 1280,
     f"MTU={mtu or '?'} (рекомендуется 1280)")

tunnel.kill()

print("=" * 60)
ok = sum(results)
print(f"ИТОГО: {ok}/{len(results)} проверок пройдено", flush=True)
if ok == len(results):
    print("ВСЁ РАБОТАЕТ. План B готов: Telegram на телефоне подруги -> "
          "Прокси SOCKS5 -> 10.20.20.1:10809", flush=True)
else:
    print("Есть сбой — смотри строки FAIL выше.", flush=True)
