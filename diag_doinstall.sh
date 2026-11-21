#!/bin/sh
B=/opt/bin/busybox
export PATH=/opt/bin:/opt/sbin:/bin:/sbin:/usr/bin:/usr/sbin
{
  $B echo "=== WAIT DNS ==="
  n=0
  while [ $n -lt 60 ]; do
    if $B nslookup bin.entware.net >/dev/null 2>&1; then
      $B echo "DNS OK (попытка $((n+1)))"
      break
    fi
    n=$((n+1))
    $B sleep 5
  done
  if $B nslookup bin.entware.net >/dev/null 2>&1; then
    $B echo "=== INSTALLER ==="
    /opt/bin/sh /opt/bin/install
    $B echo "installer_rc=$?"
  else
    $B echo "DNS ТАК И НЕ ПОДНЯЛСЯ — выход"
  fi
} >> /opt/diag.log 2>&1
