"""
Deploy Entware bootstrap на флешку Netcraze Ultra (NC-1812).
Полиглот v6 + busybox + glibc. Один запуск = полный деплой.
Флешку вставить в роутер ЗАРАНЕЕ (скрипт сам найдёт новый UUID).
Запуск: python -I deploy_entware.py
"""
import sys, os, glob, re, time, uuid
import urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netcraze_toolkit import NetcrazeAPI

HOST = "192.168.1.45"
BASE = os.path.dirname(os.path.abspath(__file__))
ASKPASS = r"C:\Users\yellow\AppData\Local\Temp\askpass-her.sh"

def ssh(cmd, timeout=30):
    import subprocess
    env = dict(os.environ)
    env.update({"SSH_ASKPASS": ASKPASS,
                "SSH_ASKPASS_REQUIRE": "force", "DISPLAY": ":0"})
    try:
        r = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no",
                            "-o", "UserKnownHostsFile=/dev/null",
                            f"admin@{HOST}", cmd],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout, env=env)
        return r.stdout.replace("\x1b[K", "")
    except Exception as ex:
        return f"SSH-ERR: {ex}"

def find_volume_uuid():
    """UUID нового EXT4-тома: из строк вставки (ext4 initialized) и монтирования."""
    log = ssh("show log", timeout=40)
    joined = re.sub(r"\n\s{20,}", "", log)
    found = []
    found += re.findall(r'"([0-9a-f]{8}-[0-9a-f-]{27}):" ext4 filesystem', joined)
    found += re.findall(r"/tmp/mnt/([0-9a-f]{8}-[0-9a-f-]{27})", joined)
    if found:
        u = found[-1]
        print(f"том флешки: {u}", flush=True)
        return u
    return None

def wait_router(timeout=300):
    print("Ждём роутер...", flush=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = ssh("show version", timeout=20)
        if r and "release" in r:
            print("роутер на связи", flush=True)
            return True
        time.sleep(10)
    return False

def main():
    api = NetcrazeAPI(HOST)
    print("auth OK", flush=True)

    # 0) найти UUID нового тома
    u = find_volume_uuid()
    if not u:
        print("!! том не найден в логе — флешка вставлена?NDMS её смонтировал?", flush=True)
        return
    U = u + ":"

    # 0.5) перепривязать opkg disk на новый UUID
    cur = ssh("show running-config")
    m = re.search(r"opkg disk (\S+)", cur)
    if m and m.group(1) != U + "/":
        print(f"opkg disk: {m.group(1)} -> {U}/", flush=True)
        ssh(f"opkg disk {U}/")
        ssh("system configuration save")

    # 1) каталоги
    for d in ["bin", "lib", "etc", "etc/init.d"]:
        r = ssh(f"mkdir {U}/{d}")
        line = r.strip().splitlines()[-1] if r.strip() else ""
        print(f"mkdir {d}: {line}", flush=True)

    # 2) список: busybox(sh+busybox) + вся lib (+libm.so.6!) + полиглот v6
    uploads = [("bin/busybox", os.path.join(BASE, "entware-stage/bin/busybox")),
               ("bin/sh",      os.path.join(BASE, "entware-stage/bin/busybox")),
               ("etc/init.d/rc.unslung", os.path.join(BASE, "rc.unslung6")),
               ("etc/init.d/doinstall", r"C:\Users\yellow\AppData\Local\Temp\diag_doinstall.sh"),
               ("lib/libm.so.6", os.path.join(BASE, "entware-stage/lib/libm-2.27.so"))]
    for f in sorted(glob.glob(os.path.join(BASE, "entware-stage/lib/*.so*"))):
        uploads.append(("lib/" + os.path.basename(f), f))

    ok, fail = 0, []
    for target, local in uploads:
        data = open(local, "rb").read()
        try:
            put = api.rci({"put": {"filename": f"{U}/{target}", "size": len(data)}})
            port = put["put"]["port"]["port"]
            b = uuid.uuid4().hex
            body = (f"--{b}\r\nContent-Disposition: form-data; name=\"port\"\r\n\r\n{port}\r\n"
                    f"--{b}\r\nContent-Disposition: form-data; name=\"Filedata\"; "
                    f"filename=\"{os.path.basename(target)}\"\r\n"
                    f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + \
                   f"\r\n--{b}--\r\n".encode()
            req = urllib.request.Request(f"http://{HOST}/fui", data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={b}"})
            r = api.op.open(req, timeout=180)
            if r.status == 200:
                ok += 1
                print(f"  OK  {target} ({len(data)} Б)", flush=True)
            else:
                fail.append(target); print(f"  {r.status} {target}", flush=True)
        except Exception as ex:
            fail.append(target); print(f"  FAIL {target}: {ex}", flush=True)

    print(f"\nЗалито: {ok}/{len(uploads)}", flush=True)
    if fail:
        print("Провалы:", fail, flush=True)
        print("Продолжаем всё равно — недостающее доустановщик скачает.", flush=True)

    # 3) контрольный ls
    print("\n--- корень тома ---", flush=True)
    print(ssh(f"ls {U}/"), flush=True)

    # 4) перезагрузка и наблюдение за установкой
    print("\nПерезагрузка роутера...", flush=True)
    ssh("system reboot")
    time.sleep(90)
    wait_router()
    time.sleep(45)
    print("\n--- лог: установка Entware ---", flush=True)
    log = ssh("show log", timeout=40)
    joined = re.sub(r"\n\s{20,}", " ", log)
    for line in joined.splitlines():
        if any(k in line for k in ("installer", "Opkg", "opkg", "unslung",
                                   "dropbear", "JBD2", "EXT4-fs error")):
            print(line.strip(), flush=True)

    # 5) порт 222?
    import socket
    try:
        s = socket.create_connection((HOST, 222), timeout=6)
        s.close()
        print("\n*** ПОРТ 222 ОТКРЫТ — ENTWARE РАБОТАЕТ! ***", flush=True)
        print("SSH: ssh -p 222 root@" + HOST + "  (пароль keenetic)", flush=True)
    except Exception:
        print("\nпорт 222 ещё закрыт — смотреть лог выше.", flush=True)

if __name__ == "__main__":
    main()
