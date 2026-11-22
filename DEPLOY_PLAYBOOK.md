# Deploy Playbook — воспроизведение Plan B с нуля

Полная процедура развёртывания шлюза подруги на чистой флешке.
Проверено: 21-22.11.2026. Время: ~40 мин, из них 30 — ожидания загрузок.

## 0. Что нужно
- Роутер Netcraze Ultra (NC-1812), прошивка 5.1.9+, компонент OPKG
- Флешка USB ≥1ГБ (брендовая; no-nameGeneric может сыпать I/O-ошибки на USB роутера)
- ПК в той же LAN, DiskGenius (формат ext4), Python 3.12 с netcraze_toolkit.py

## 1. Формат флешки (ПК)
DiskGenius → диск → раздел → «Форматирование текущего раздела» → EXT4.
Безопасное извлечение → в роутер.

## 2. Права 0755 (КРИТИЧНО)
/fui-загрузка создаёт файлы 0644; Reality не работает без +x на bin/sh.
ДВА ПУТИ:
a) После загрузок — флешку в ПК → sb_fix.py (elevated, UAC): патчит иноды
   (0755 на bin/sh, bin/busybox, init.d/*, ld-linux) + гасит has_journal и
   metadata_csum в суперблоке (журнал иначе откатывает правки!). 
б) Или сразу после формата: sb_fix не нужен, если загрузки идут через
   tunnel-shell с root-cp (см. шаг 5).

## 3. Загрузка бустрапа (deploy_entware.py)
python -I deploy_entware.py — сам найдёт UUID, привяжет OPKG, создаст
каталоги, зальёт polyglot (script+embedded tar.gz = полный Entware-инсталлятор
с DNS-ожиданием), busybox+glibc копии (bin/sh!), перезагрузит, покажет лог.
Инсталлятор сам доустановит пакеты с bin.entware.net (aarch64-k3.10).

## 4. Проверка
ssh -p 2223 root@<router> (пароль keenetic) → xray version → 26.x ✓

## 5. Конфиг xray (ВАЖНО — версия!)
26.10+ официально/Yichya СБРОСЫВАЕТ Reality к trom-ka с Netcraze-транзитом;
рабочий = yichya 26.9.9 (см. bisect3). Конфиг: prox-reserve = рабочий канал
(trom-ka tcp+reality). НЕ использовать balancer с мёртвым prox-f3 (маскировка
microsoft.com выглядит «живой» для leastPing — выбор ломает трафик).
Маршрут: ip route add 77.221.140.43/32 dev nwg1 src 10.20.20.2 (туннель =
одинарный NAT; двойной NAT транзит ломает Reality-рукопожатия).

## 6. Firewall (S99fw v5)
Двухуровневые маршруты (туннель metric10 / WAN metric100) + REDIRECT
телеграм-подсетей (91.108/16, 149.154.160/20, 95.161.76/22) → 1501
(её xray transparent) + REJECT udp/443 в TG-подсетях (QUIC bypass).

## 7. Удалённый доступ
WG-туннель держится keepalive 25с через любой NAT. С Keenetic-стороны:
ssh admin@10.20.20.2 (NDMS), http://10.20.20.2 (веб), ssh -p 2223
root@10.20.20.2 (Entware). isolate-private OFF на Keenetic ОБЯЗАТЕЛЬНО
(иначе LAN→WG транзит режется изоляцией сегментов).
