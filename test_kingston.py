import os, random, struct, time, re, subprocess

OUT = r"C:\Users\yellow\AppData\Local\Temp\kingston_test.txt"
out_lines = []

def p(s):
    out_lines.append(str(s))
    try:
        print(s, flush=True)
    except Exception:
        pass

r = subprocess.run(["powershell", "-NoProfile", "-Command",
    "Get-Disk | Where-Object BusType -eq 'USB' | Select-Object Number,Size | ConvertTo-Json"],
    capture_output=True, text=True, timeout=60)
nums = re.findall(r'"Number"\s*:\s*(\d+)', r.stdout)
sizes = re.findall(r'"Size"\s*:\s*(\d+)', r.stdout)
disk = None
for n, s in zip(nums, sizes):
    gb = int(s) / 2**30
    if 10 < gb < 20:
        disk = n
        p(f"цель: PhysicalDrive{n} ({gb:.2f} GB)")
if disk is None:
    p("!! USB-диск ~15GB не найден")
    with open(OUT, "w", encoding="utf-8") as fo:
        fo.write("\n".join(out_lines))
    raise SystemExit
dev = rf"\\.\PhysicalDrive{disk}"

# размонтировать NTFS-том (иначе Windows не даст писать raw)
r2 = subprocess.run(["powershell", "-NoProfile", "-Command",
    f"Get-Partition -DiskNumber {disk} | Select-Object -ExpandProperty DriveLetter | ConvertTo-Json"],
    capture_output=True, text=True, timeout=60)
letters = re.findall(r'"[^"]*"\s*:\s*"?([A-Z]:?)"?', r2.stdout) or re.findall(r'([A-Z])"', r2.stdout)
letters = re.findall(r'([A-Z])(?=[",\s\]])', r2.stdout)
for L in set(letters):
    subprocess.run(["mountvol", f"{L}:", "/P"], capture_output=True, timeout=30)
    p(f"том {L}: размонтирован (mountvol /P)")
subprocess.run(["powershell", "-NoProfile", "-Command",
    f"Set-Disk -Number {disk} -IsOffline $true; Set-Disk -Number {disk} -IsReadOnly $false"],
    capture_output=True, timeout=60)
p(f"диск {disk}: offline + read-write")
p("")

def aligned_read(f, off, length):
    win = off // 512 * 512
    delta = off - win
    span = (delta + length + 511) // 512 * 512
    f.seek(win)
    blob = f.read(span)
    return blob[delta:delta+length]

def aligned_write(f, off, data):
    win = off // 512 * 512
    delta = off - win
    span = (delta + len(data) + 511) // 512 * 512
    f.seek(win)
    blob = bytearray(f.read(span))
    blob[delta:delta+len(data)] = data
    f.seek(win)
    f.write(bytes(blob))
    f.flush()
    os.fsync(f.fileno())

f = open(dev, "rb")
f.seek(0)
mbr = f.read(512)
p(f"MBR: {mbr[510:512].hex()}")
for i in range(4):
    e = mbr[446+i*16:446+(i+1)*16]
    if e[4] != 0:
        st = struct.unpack("<I", e[8:12])[0]
        sz = struct.unpack("<I", e[12:16])[0]
        p(f"раздел {i+1}: тип=0x{e[4]:02x} старт={st}с размер={sz*512/2**30:.2f} ГБ")
p("")
p("=== чтение 1 МБ по всей длине ===")
total = 15.2 * 2**30
for og in [0.001, 1, 3, 6, 9, 12, 14.5]:
    off = int(og * 2**30)
    try:
        t0 = time.time()
        d = aligned_read(f, off, 1024*1024)
        dt = time.time() - t0
        u = len(set(d[:65536]))
        p(f"{og:5.1f} ГБ: {dt:4.2f}с уникальных {u:5d}{'  << НУЛИ' if u <= 1 else ''}")
    except Exception as ex:
        p(f"{og:5.1f} ГБ: ОШИБКА {ex}")
f.close()

p("")
p("=== точечная запись 512К + сверка ===")
def wr1(off_gb, label):
    off = int(off_gb * 2**30) // 512 * 512
    g = open(dev, "r+b")
    pat = random.randbytes(512*1024)
    aligned_write(g, off, pat)
    back = aligned_read(g, off, 512*1024)
    g.close()
    ok = back == pat
    p(f"запись {label} ({off_gb:.1f} ГБ): {'СОВПАЛО' if ok else '!!! ЧИТАЕТСЯ ДРУГОЕ'}")
    return ok

p("")
p("=== НЕПРЕРЫВНАЯ запись 16 МБ + сверка (именно тут умирала старая) ===")
def sustained(off_gb, mb):
    off = int(off_gb * 2**30) // 512 * 512
    chunk = random.randbytes(1024*1024)
    g = open(dev, "r+b")
    t0 = time.time()
    try:
        for i in range(mb):
            aligned_write(g, off + i*1024*1024, chunk if i % 2 == 0 else random.randbytes(1024*1024))
        dt_w = time.time() - t0
        p(f"  запись {mb} МБ за {dt_w:.1f}с ({mb/dt_w:.1f} МБ/с)")
        ok = True
        for i in range(mb):
            back = aligned_read(g, off + i*1024*1024, 1024*1024)
            if len(back) != 1024*1024:
                ok = False; p(f"  !! блок {i}: короткое чтение"); break
        g.close()
        p(f"  перечитано 16 МБ: {'ВСЁ ЦЕЛО ✓' if ok else '!! ПОВРЕЖДЕНО'}")
        return ok
    except Exception as ex:
        p(f"  !! ОШИБКА: {ex}")
        try: g.close()
        except: pass
        return False

res = []
res += [wr1(0.05, "начало"), wr1(7.0, "середина"), wr1(14.8, "хвост")]
res.append(sustained(1.0, 16))
p("")
p(f"ИТОГ: {sum(res)}/{len(res)} проверок пройдено")
subprocess.run(["powershell", "-NoProfile", "-Command",
    f"Set-Disk -Number {disk} -IsOffline $false"], capture_output=True, timeout=60)
p("диск возвращён в online")
with open(OUT, "w", encoding="utf-8") as fo:
    fo.write("\n".join(out_lines))
print("DONE", flush=True)
