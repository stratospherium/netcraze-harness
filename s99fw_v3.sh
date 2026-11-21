#!/bin/sh
export PATH=/opt/bin:/opt/sbin:/bin:/sbin:/usr/bin:/usr/sbin
CHAIN=tg_tunnel
case "$1" in
  stop)
    iptables -t nat -D PREROUTING -s 192.168.2.0/24 -d 91.108.0.0/16 -p tcp -j DNAT --to-destination 10.20.20.1:1501 2>/dev/null
    iptables -t nat -D PREROUTING -s 192.168.2.0/24 -d 149.154.160.0/20 -p tcp -j DNAT --to-destination 10.20.20.1:1501 2>/dev/null
    iptables -t nat -D PREROUTING -s 192.168.2.0/24 -d 95.161.76.0/22 -p tcp -j DNAT --to-destination 10.20.20.1:1501 2>/dev/null
    iptables -D FORWARD -s 192.168.2.0/24 -d 91.108.0.0/16 -p udp -j REJECT 2>/dev/null
    iptables -D FORWARD -s 192.168.2.0/24 -d 149.154.160.0/20 -p udp -j REJECT 2>/dev/null
    ;;
  *)
    # Телеграм подсети -> через WG туннель на прозрачный порт xray (10.20.20.1:1501)
    for r in 91.108.4.0/22 91.108.8.0/22 91.108.12.0/22 91.108.16.0/22 91.108.20.0/22 91.108.56.0/22 149.154.160.0/20 95.161.76.0/22; do
      iptables -C PREROUTING -s 192.168.2.0/24 -d $r -p tcp -j DNAT --to-destination 10.20.20.1:1501 2>/dev/null || iptables -t nat -A PREROUTING -s 192.168.2.0/24 -d $r -p tcp -j DNAT --to-destination 10.20.20.1:1501
    done
    # QUIC (udp 443) в TG-подсетях блокируем, чтобы клиент не уходил из tcp-туннеля
    iptables -C FORWARD -s 192.168.2.0/24 -d 149.154.160.0/20 -p udp -j REJECT 2>/dev/null || iptables -I FORWARD -s 192.168.2.0/24 -d 149.154.160.0/20 -p udp -j REJECT
    ;;
esac
