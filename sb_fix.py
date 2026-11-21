"""
Точечный фикс суперблока ext4 флешки:
 1. has_journal OFF  (incompat 0x4)  — журнал больше не откатывает правки
 2. metadata_csum OFF (ro_compat 0x400) — ядро не проверяет чексуммы инодов/sb
 3. s_state = 1 (EXT4_VALID_FS) — снять флаг "fs with errors"
 4. убедиться, что 4 инода-цели имеют mode 0755 (записать, если нет)
Запускать с админ-правами.
"""
import struct, os, re, subprocess

OUT = r"C:\Users\yellow\AppData\Local\Temp\sb_fix_log.txt"
out_lines = []

def p(s):
    out_lines.append(str(s))
    try:
        print(s, flush=True)
    except Exception:
        pass

class Ext4:
    def __init__(self, f):
        self.f = f
        f.seek(0)
        mbr = f.read(512)
        self.po = 0
        gpt = False
        for i in range(4):
            e = mbr[446+i*16:446+(i+1)*16]
            if e[4] == 0xEE:
                gpt = True
                break
            if e[4] != 0:
                self.po = struct.unpack("<I", e[8:12])[0] * 512
                break
        if gpt:
            f.seek(512)  # LBA1: GPT header
            hdr = f.read(512)
            if hdr[:8] == b"EFI PART":
                pe_lba = struct.unpack("<Q", hdr[72:80])[0]
                f.seek(pe_lba * 512)
                ent = f.read(128)
                first_lba = struct.unpack("<Q", ent[32:40])[0]
                self.po = first_lba * 512
                p(f"GPT: раздел с LBA {first_lba} (оффсет {self.po})")
            else:
                raise RuntimeError("GPT header не найден")
        self.sb_off = self.po + 1024
        self.read_sb()

    def read_sb(self):
        self.f.seek(self.sb_off)          # po+1024 всегда кратно 512
        self.sb = bytearray(self.f.read(1024))
        sb = self.sb
        assert sb[56:58] == b"\x53\xef", "не ext4"
        self.ipg = struct.unpack("<I", sb[40:44])[0]
        self.bs = 1024 << struct.unpack("<I", sb[24:28])[0]
        self.isize = struct.unpack("<H", sb[88:90])[0]
        self.inc = struct.unpack("<I", sb[96:100])[0]
        self.ro = struct.unpack("<I", sb[100:104])[0]
        self.state = struct.unpack("<H", sb[58:60])[0]
        self.uuid = bytes(sb[104:120])
        self.dsize = struct.unpack("<H", sb[254:256])[0] or 32
        self._gdt = self.po + 1 * self.bs

    def write_sb(self):
        sec = self.sb_off // 512 * 512
        self.f.seek(sec)
        blob = bytearray(self.f.read(1024))
        blob[0:1024] = bytes(self.sb)
        self.f.seek(sec)
        self.f.write(bytes(blob))
        self.f.flush()

    def _itable(self, ino):
        g = (ino - 1) // self.ipg
        self.f.seek(self._gdt + g * self.dsize)
        gd = self.f.read(self.dsize)
        lo = struct.unpack("<I", gd[8:12])[0]
        hi = struct.unpack("<I", gd[38:42])[0] if self.dsize >= 64 else 0
        return self.po + ((hi << 32) | lo) * self.bs

    def inode(self, ino):
        off = self._itable(ino) + (ino - 1) % self.ipg * self.isize
        win = off // 512 * 512
        delta = off - win
        span = (delta + self.isize + 511) // 512 * 512
        self.f.seek(win)
        blob = self.f.read(span)
        return off, bytearray(blob[delta:delta + self.isize])

    def write_inode_mode(self, off, ino, mode):
        _, data = self.inode(ino)
        data[0:2] = struct.pack("<H", mode)
        win = off // 512 * 512
        delta = off - win
        span = (delta + self.isize + 511) // 512 * 512
        self.f.seek(win)
        blob = bytearray(self.f.read(span))
        blob[delta:delta + self.isize] = bytes(data)
        self.f.seek(win)
        self.f.write(bytes(blob))
        self.f.flush()

    def readdir(self, ino):
        _, data = self.inode(ino)
        size = struct.unpack("<I", data[4:8])[0]   # i_size_lo @4
        res = bytearray()
        flags = struct.unpack("<I", data[32:36])[0]
        if flags & 0x80000:
            magic = struct.unpack("<H", data[40:42])[0]
            if magic == 0xF30A:
                ee_len = struct.unpack("<H", data[56:58])[0]
                hi = struct.unpack("<H", data[58:60])[0]
                lo = struct.unpack("<I", data[60:64])[0]
                self.f.seek(self.po + ((hi << 32) | lo) * self.bs)
                res += self.f.read(ee_len * self.bs)
        else:
            for b in struct.unpack("<12I", data[40:88]):
                if b:
                    self.f.seek(self.po + b * self.bs)
                    res += self.f.read(self.bs)
        raw = bytes(res[:size])
        out = {}
        pos = 0
        while pos + 8 <= len(raw):
            e_ino = struct.unpack("<I", raw[pos:pos+4])[0]
            rlen = struct.unpack("<H", raw[pos+4:pos+6])[0]
            nlen = raw[pos+6]
            if rlen < 8:
                break
            if e_ino and nlen and pos + 8 + nlen <= len(raw):
                out[raw[pos+8:pos+8+nlen].decode("utf-8", "replace")] = e_ino
            pos += rlen
        return out

def main():
    r = subprocess.run(["powershell", "-NoProfile", "-Command",
        "Get-Disk | Where-Object BusType -eq 'USB' | Select-Object Number,Size | ConvertTo-Json"],
        capture_output=True, text=True, timeout=60)
    nums = re.findall(r'"Number"\s*:\s*(\d+)', r.stdout)
    sizes = re.findall(r'"Size"\s*:\s*(\d+)', r.stdout)
    disk = None
    for n, s in zip(nums, sizes):
        gb = int(s) / 2**30
        if 1.0 < gb < 64.0:
            disk = n
            p(f"цель: PhysicalDrive{n} ({gb:.2f} GB)")
    if disk is None:
        p("!! USB-диск не найден")
        return
    dev = rf"\\.\PhysicalDrive{disk}"
    f = open(dev, "r+b")
    fs = Ext4(f)
    p(f"superblock: inc={hex(fs.inc)} ro={hex(fs.ro)} state={fs.state} "
      f"metadata_csum={'ВКЛ' if fs.ro & 0x400 else 'выкл'} "
      f"has_journal={'ВКЛ' if fs.inc & 0x4 else 'выкл'}")

    changed = False
    if fs.inc & 0x4:
        fs.sb[96:100] = struct.pack("<I", fs.inc & ~0x4)
        changed = True
        p("1) has_journal -> ВЫКЛЮЧЕН (журнал больше не откатывает правки)")
    if fs.ro & 0x400:
        fs.sb[100:104] = struct.pack("<I", fs.ro & ~0x400)
        changed = True
        p("2) metadata_csum -> ВЫКЛЮЧЕН (чексуммы не проверяются)")
    if fs.state != 1:
        fs.sb[58:60] = struct.pack("<H", 1)
        changed = True
        p(f"3) s_state {fs.state} -> 1 (EXT4_VALID_FS)")
    if changed:
        fs.write_sb()
        fs.read_sb()
        ok = not (fs.ro & 0x400) and not (fs.inc & 0x4) and fs.state == 1
        p(f"   перечитано: inc={hex(fs.inc)} ro={hex(fs.ro)} state={fs.state} "
          f"{'OK' if ok else '!! НЕ ЗАПИСАЛОСЬ'}")
    else:
        p("суперблок уже в нужном состоянии")
    p("")

    # --- режимы целевых инодов ---
    targets = ["/bin/sh", "/bin/busybox", "/etc/init.d/rc.unslung", "/etc/init.d/doinstall",
               "/lib/ld-linux-aarch64.so.1", "/lib/ld-2.27.so"]
    for path in targets:
        parts = path.strip("/").split("/")
        cur = 2
        try:
            for part in parts[:-1]:
                d = fs.readdir(cur)
                cur = d[part]
            d = fs.readdir(cur)
            ino = d[parts[-1]]
            off, data = fs.inode(ino)
            m = struct.unpack("<H", data[0:2])[0]
            if m != 0o100755:
                fs.write_inode_mode(off, ino, 0o100755)
                _, chk = fs.inode(ino)
                m2 = struct.unpack("<H", chk[0:2])[0]
                p(f"  {path}: {oct(m)} -> {oct(m2)} {'OK' if m2 == 0o100755 else '!!'}")
            else:
                p(f"  {path}: mode {oct(m)} — уже 755")
        except Exception as ex:
            p(f"  {path}: ОШИБКА {ex}")
    p("")
    p("ГОТОВО — можно переставлять флешку в роутер")
    f.close()
    with open(OUT, "w", encoding="utf-8") as fo:
        fo.write("\n".join(out_lines))

if __name__ == "__main__":
    main()
