"""
wifi_setup.py — идемпотентная настройка Wi-Fi на её роутере через туннель.

Правило: «готово» = только после независимой проверки сохранённого
состояния из НОВОГО подключения.

Целевое состояние:
  WF_Party     : psk 1212121212, WPA2 (без WPA3 — старые телефоны)
  WF_Party_5G  : psk 1212121212, WPA2

Запуск: python -I wifi_setup.py
"""
import subprocess, sys, time, os, re

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HOST = "10.20.20.2"
ASKPASS = r"C:\Users\yellow\AppData\Local\Temp\askpass-her.sh"
ENV = {**os.environ,
       "SSH_ASKPASS": ASKPASS, "SSH_ASKPASS_REQUIRE": "force",
       "DISPLAY": ":0", "MSYS_NO_PATHCONV": "1"}

SYSNAMES = {"WifiMaster0/AccessPoint0": "WF_Party",
            "WifiMaster1/AccessPoint0": "WF_Party_5G"}

PSK = "1212121212"

def say(s):
    print(s, flush=True)

def clean(s):
    return s.replace("\x1b[K", "").replace("\r", "")

def ssh_cmd(cli_line, timeout=45):
    """Одна NDMS-команда (независимое чтение)."""
    env = {**ENV, "SSH_ASKPASS": ASKPASS}
    r = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no",
         "-o", "UserKnownHostsFile=/dev/null", f"admin@{HOST}", cli_line],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=env)
    return clean(r.stdout)

def get_state():
    """Wi-Fi из running-config (независимое чтение)."""
    out = ssh_cmd("show running-config")
    say(f"  (running-config: {len(out)} байт)")
    state = {}
    for sysname, label in SYSNAMES.items():
        m = re.search(r"interface " + re.escape(sysname) +
                      r"\r?\n((?:[^\n]*\r?\n)*?)(?=interface |\Z)", out)
        blk = m.group(1) if m else ""
        ssid = re.search(r"ssid (\S+)", blk)
        key = re.search(r"encryption key 1 (\S+)", blk)
        state[label] = {
            "ssid": ssid.group(1) if ssid else None,
            "key": key.group(1) if key else None,
            "wpa2": "encryption wpa2" in blk,
            "wpa3": "encryption wpa3" in blk,
        }
    return state

def apply_config():
    """Применение: NDMS-команды построчно через ssh -tt. Таймаут не ошибка:
    команды применяются до истечения, ssh просто висит после exit."""
    lines = [""] * 8
    for sysname, label in SYSNAMES.items():
        lines += [f"interface {sysname}",
                  f"ssid {label}",
                  "encryption wpa2",
                  "encryption key 1 " + PSK,
                  "no encryption wpa3",
                  "exit"]
    lines += ["system configuration save"]
    inp = "\n".join(lines) + "\nexit\n"
    try:
        subprocess.run(
            ["ssh", "-tt", "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null", f"admin@{HOST}"],
            input=inp, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=150, env=ENV)
        say("  batch: сессия завершена (таймаут после exit — норма)")
    except subprocess.TimeoutExpired:
        say("  batch: сессия длиннее таймаута — команды уже применились")
    except Exception as ex:
        say(f"  batch: {str(ex)[:60]}")

def main():
    say("=" * 60)
    say("WIFI SETUP — идемпотентная настройка с проверкой сохранения")
    say("=" * 60)

    say("\n[1/4] Текущее состояние (независимое чтение):")
    st = get_state()
    for label, s in st.items():
        say(f"  {label}: ssid={s['ssid']} key={s['key']} wpa2={s['wpa2']} wpa3={s['wpa3']}")

    need = any(
        st.get(label, {}).get("ssid") != label or
        st.get(label, {}).get("key") != PSK or
        not st.get(label, {}).get("wpa2") or
        st.get(label, {}).get("wpa3")
        for label in SYSNAMES.values())

    if need:
        say("\n[2/4] Применение (NDMS batch):")
        apply_config()
    else:
        say("\nСостояние уже соответствует целевому — применение не требуется.")

    say("\n[3/4] Независимая проверка (новое подключение):")
    time.sleep(3)
    st2 = get_state()
    all_ok = True
    for label, s in st2.items():
        ok = (s.get("ssid") == label and s.get("key") == PSK and
              s.get("wpa2") and not s.get("wpa3"))
        all_ok = all_ok and ok
        say(f"  {label}: ssid={s.get('ssid')} key={s.get('key')} "
            f"wpa2={s.get('wpa2')} wpa3={s.get('wpa3')} {'OK' if ok else 'FAIL'}")

    say("\n[4/4] Вердикт:")
    if all_ok:
        say("ВСЁ ПРИМЕНЕНО И ПРОВЕРЕНО ИЗ НОВОГО ПОДКЛЮЧЕНИЯ.")
        say("Телефон: забыть старую сеть → WF_Party / 1212121212")
    else:
        say("ЕСТЬ РАСХОЖДЕНИЯ — смотри лог выше.")

if __name__ == "__main__":
    main()
