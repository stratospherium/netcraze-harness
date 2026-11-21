"""
Netcraze/Keenetic Harness — обвязка для управления роутерами Netcraze (KeeneticOS 5.x).

Выученные уроки (2026-11, proj sess_afa526f5):
  1. АВТОРИЗАЦИЯ (web API): GET /auth → 401 + X-NDM-Challenge/X-NDM-Realm.
     Клиент: md5hex = md5("{login}:{realm}:{password}"), ответ = sha256(chal + md5hex),
     POST /auth JSON {login, password}. Нужны cookies (сессия привязана к куке).
  2. ПАРОЛЬ ЧЕРЕЗ CLI: `password plain X` — ПРАВИЛЬНО (обновляет и nt, и realm-md5).
     `password md5 <hash>` — ОПАСНО: поле md5 хранит md5("{login}:{realm}:{pwd}"),
     сырой md5 пароля ломает ВСЮ авторизацию (web 401 + SSH denied) без возможности
     отката без сброса. НЕ ИСПОЛЬЗОВАТЬ без крайней необходимости.
  3. SSH: каждая команда = отдельная сессия, контекст (config-if и т.п.) не сохраняется
     между ssh-вызовами. Пакеты команд — через один TTY-сеанс (см. cli_batch).
     Точка с запятой в CLI не работает.
  4. ПИРЫ WIREGUARD: вложенные команды пира: allow-ips / endpoint / keepalive-interval
     (НЕ wireguard allowed-ips и т.д.). Ключ пира = публичный ключ УДАЛЁННОЙ стороны.
     Firewall-правило: access-list _WEBADMIN_<iface> permit udp 0.0.0.0 0.0.0.0 0.0.0.0 0.0.0.0 port eq <port>.
  5. ПРОШИВКА ОФЛАЙН: полный образ с components — osvault.netcraze.ru/<модель>/<версия>/
     (доступен часто только через VPN; cdn.netcraze.ru бывает сломан серверно).
     Загрузка в роутер: POST /fui/ multipart (port=<токен>, Filedata=<файл>),
     где токен = RCI {"put":{"filename":"firmware/<имя>","size":N}} → put.port.port,
     и во время загрузки нужно ОПРАШИВАТЬ put (executeContinued) каждые ~2с.
  6. RCI API: POST /rci/ {"show":{"version":{}}} — вложенная структура = путь команды.
  7. Компоненты: `components list` → `components install <name>` → `components commit`
     (каждая команда отдельным вызовом; мультилайн через ';' — parse error).
"""
import json, hashlib, time, threading, uuid
import urllib.request, urllib.error, http.cookiejar


class NetcrazeAPI:
    """Управление роутером по HTTP (auth + RCI + fui upload)."""

    def __init__(self, host, login="admin", password="Trololo123", https=False, verify=False):
        self.base = ("https://" if https else "http://") + host
        self.login, self.password = login, password
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        if not verify:
            import ssl
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self.op.add_handler(urllib.request.HTTPSHandler(context=ctx))
        self._auth()

    def _auth(self):
        req = urllib.request.Request(self.base + "/auth")
        try:
            self.op.open(req, timeout=10)
            raise RuntimeError("ожидался 401 с challenge")
        except urllib.error.HTTPError as e:
            chal = e.headers.get("X-NDM-Challenge") or ""
            realm = e.headers.get("X-NDM-Realm") or ""
        md5hex = hashlib.md5(f"{self.login}:{realm}:{self.password}".encode()).hexdigest()
        resp = hashlib.sha256((chal + md5hex).encode()).hexdigest()
        body = json.dumps({"login": self.login, "password": resp}).encode()
        req = urllib.request.Request(self.base + "/auth", data=body,
                                     headers={"Content-Type": "application/json"})
        r = self.op.open(req, timeout=15)
        return r.status

    def rci(self, obj, timeout=30):
        """POST /rci/ — вложенный JSON = путь команды: {"show":{"version":{}}}."""
        req = urllib.request.Request(self.base + "/rci/", data=json.dumps(obj).encode(),
                                     headers={"Content-Type": "application/json"})
        r = self.op.open(req, timeout=timeout)
        return json.loads(r.read().decode("utf-8", errors="replace"))

    def cli(self, command, timeout=30):
        """NDMS CLI-команда через RCI (кратковременные команды)."""
        return self.rci({"cli": {"command": command}}, timeout=timeout) if False else self.rci_read(command)

    def rci_read(self, cli_path):
        """Прочитать вывод show-команды: rci_read('show/version') или rci_read('show/running-config')."""
        obj = {}
        node = obj
        parts = cli_path.split("/")
        for i, p in enumerate(parts[:-1]):
            node[p] = {}
            node = node[p]
        node[parts[-1]] = {}
        res = self.rci(obj, timeout=timeout if False else 30)
        return res

    def running_config(self):
        m = self.rci_read("show/running-config")["show"]["running-config"]["message"]
        return "\n".join(m)

    def version(self):
        return self.rci_read("show/version")["show"]["version"]

    def fui_upload(self, slot, filename, local_path, progress=None):
        """Загрузка файла в слот роутера (slot='firmware' для прошивки).
        Требует keepalive-опрос put во время передачи."""
        size = __import__("os").path.getsize(local_path)
        put = self.rci({"put": {"filename": f"{slot}/{filename}", "size": size}})
        port = put["put"]["port"]["port"]
        stop = threading.Event()
        def keepalive():
            while not stop.is_set():
                try:
                    self.rci({"put": {"filename": f"{slot}/{filename}", "size": size}}, t=15)
                except Exception:
                    pass
                time.sleep(2)
        t = threading.Thread(target=keepalive, daemon=True); t.start()
        data = open(local_path, "rb").read()
        b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"port\"\r\n\r\n{port}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"Filedata\"; filename=\"{filename}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{b}--\r\n".encode()
        try:
            req = urllib.request.Request(self.base + "/fui", data=body,
                headers={"Content-Type": f"multipart/form-data; boundary={b}"})
            r = self.op.open(req, timeout=1800)
            out = r.read().decode(errors="replace")
            stop.set()
            return out
        except Exception as e:
            stop.set()
            raise

    def save(self):
        return self.rci({"system": {"configuration": {"save": {}}}})

    def reboot(self):
        return self.rci({"system": {"reboot": {}}})


class NetcrazeSSH:
    """Пакетный драйвер NDMS CLI через SSH (TTY). Контекст команд сохраняется в одном сеансе.
    Требует SSH_ASKPASS-хелпер (файл, выводящий пароль) и переменные окружения."""

    def __init__(self, target, askpass_path, timeout_total=600):
        import os, subprocess
        env = dict(os.environ)
        env["SSH_ASKPASS"] = askpass_path
        env["SSH_ASKPASS_REQUIRE"] = "force"
        env.setdefault("DISPLAY", ":0")
        self.proc = subprocess.Popen(
            ["ssh", "-tt", "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null", target],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, text=True, encoding="utf-8", errors="replace", bufsize=1)
        self.lines = []
        self._read(6)

    def _read(self, sec):
        end = time.time() + sec
        while time.time() < end:
            try:
                line = self.proc.stdout.readline()
                if not line:
                    time.sleep(0.1); continue
                clean = line.replace("\x1b[K", "").rstrip("\n")
                self.lines.append(clean)
                print("<<", clean)
            except Exception:
                break

    def send(self, cmd, wait=3):
        print(">>", cmd)
        self.proc.stdin.write(cmd + "\n"); self.proc.stdin.flush()
        self._read(wait)

    def close(self):
        try:
            self.proc.stdin.write("exit\n"); self.proc.stdin.flush()
            self._read(2)
            self.proc.kill()
        except Exception:
            pass


def cli_batch(target, askpass_path, commands, wait=3):
    """Одноразовая batch-сессия: список CLI-команд одним TTY-сеансом."""
    s = NetcrazeSSH(target, askpass_path)
    try:
        for c in commands:
            s.send(c, wait)
    finally:
        s.close()
