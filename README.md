# Netcraze Harness

Обвязка для управления роутерами Netcraze / Keenetic (KeeneticOS 5.x) по HTTP API и SSH.
Родилась из реальной операции по настройке роутера подруги (ноябрь 2026) — все уроки
вбиты в код и в этот README.

## Файлы

- `netcraze_toolkit.py` — библиотека: `NetcrazeAPI` (HTTP auth + RCI + загрузка прошивки)
  и `NetcrazeSSH` / `cli_batch` (TTY-драйвер NDMS CLI по SSH).

## Быстрый старт

```python
from netcraze_toolkit import NetcrazeAPI, cli_batch

rt = NetcrazeAPI("192.168.1.45", "admin", "<пароль>")
print(rt.version())                 # версия ОС
cfg = rt.running_config()           # running-config текстом
rt.save()                           # system configuration save
out = rt.fui_upload("firmware", "NC-1812_stable_5.1.8.bin", "NC-1812_stable_5.1.8.bin")  # прошивка офлайн-образом

# CLI-пакет по SSH (контекст команд сохраняется внутри одного сеанса):
cli_batch("admin@<роутер-ip>", r"C:\path\to\askpass.sh", [
    "interface Wireguard1",
    "allow-ips 10.20.20.1/32",
    "exit",
    "system configuration save",
])
```

## Уроки (не нарушать!)

1. **Пароль через CLI:** только `password plain <пароль>` (обновляет и NT-, и realm-md5-хэш).
   `password md5 <hash>` — поле md5 хранит **realm-форму** `md5("login:realm:пароль")`, а НЕ
   сырой md5 пароля. Записать туда сырой md5 = сломать ВСЮ авторизацию (web 401 + SSH denied)
   без возможности отката. Проверка NT-хэша: `certutil -hashfile <utf-16le файл без BOM> MD4`.
2. **Авторизация web API:** GET /auth → 401 + X-NDM-Challenge/X-NDM-Realm;
   md5hex = md5("{login}:{realm}:{пароль}"); ответ = sha256(challenge + md5hex);
   POST /auth JSON {login, password}; обязательны cookies.
3. **SSH CLI:** команды в одном сеансе делят контекст (config-if и т.п.); между ssh-вызовами
   контекст теряется. `;` в CLI не работает — одна команда = одна строка/отправка.
4. **WireGuard пиры:** вложенные команды пира: `allow-ips` / `endpoint` / `keepalive-interval`.
   Ключ пира = публичный ключ УДАЛЁННОЙ стороны (самопир → ENOKEY).
   Firewall: `access-list _WEBADMIN_<iface>` + `permit udp 0.0.0.0 0.0.0.0 0.0.0.0 0.0.0.0 port eq <port>`.
5. **Прошивка офлайн:** полные образы — `https://osvault.netcraze.ru/<модель>/<версия>/`
   (может требовать VPN; cdn.netcraze.ru периодически ломается серверно, «Invalid domain name»).
   Имя файла: `NC-<index>_<канал>_<версия>.bin`. Полный набор = все компоненты сразу.
6. **Загрузка в роутер:** RCI `{"put":{"filename":"<slot>/<имя>","size":N}}` → токен
   `put.port.port` → POST /fui/ multipart (port=токен, Filedata=файл) + опрос put каждые ~2 с
   во время передачи. Веб-сервер роутера хрупкий: 405/502 фляпают, под нагрузкой виснет —
   помогает только передёр питания. Не слать 31 МБ POST-ы без keepalive.
7. **Компоненты:** `components list` → `components install <name>` → `components commit`.
   Каждая — отдельный вызов. CDN иногда лежит: тогда офлайн-образ (п.5) — единственный путь.
8. **RCI:** POST /rci/ {"show":{"version":{}}} — вложенный JSON = путь CLI-команды.
9. **Web UI из WAN:** по умолчанию закрыт (security-level public у WAN). Открытие:
   `interface <WAN>` → `security-level private` (временно!) или «Доступ из интернета» в UI.
   После настройки — закрыть обратно.
10. **Сброс в заводское + wizard:** первичная настройка доступна ТОЛЬКО изнутри его сети
    (Wi-Fi/LAN). Из внешней сети веб-морда до настройки не видна. Телефон — легальный клиент.

## История операции (проект «роутер подруги», ноябрь 2026)

- Цель: автономный Xray на её роутере + Telegram без блокировок.
- Итог: Plan B (WireGuard-туннель её→его роутер + его xray) работает; автономный Xkeen
  в ожидании починки CDN / офлайн-прошивки.

## TODO в харнес

- [ ] paramiko-транспорт вместо askpass (чистые пароли в коде)
- [ ] auto-detect модели по osvault (NC-<index>)
- [ ] не хранить пароли в репозитории (askpass-файлы — во временной папке, ротировать)
