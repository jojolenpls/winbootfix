# shellcheck shell=sh
# Disable the display driver service, drop an x86 DLL in System32, damage a protected system file.
break_system() {
    cat <<'X'
win=$(lsblk -rno PATH,FSTYPE | awk '$2=="ntfs"{print $1}' | while read -r d; do
  mkdir -p /mnt/w; ntfs-3g -o ro "$d" /mnt/w 2>/dev/null || continue
  [ -d /mnt/w/Windows/System32 ] && echo "$d"; umount /mnt/w; done | head -n1)
ntfs-3g "$win" /mnt/w
python3 - <<'PY'
import hivex, struct
h = hivex.Hivex("/mnt/w/Windows/System32/config/SYSTEM", write=True)
sel = h.node_get_child(h.root(), "Select")
cur = h.value_dword(h.node_get_value(sel, "Current"))
svc = h.node_get_child(h.node_get_child(h.node_get_child(h.root(), "ControlSet%03d" % cur), "Services"), "viogpudo")
if svc:
    h.node_set_value(svc, {"key": "Start", "t": 4, "value": struct.pack("<I", 4)})
    h.commit(None)
    print("viogpudo disabled")
PY
cp /mnt/w/Windows/SysWOW64/msvcrt.dll /mnt/w/Windows/System32/wbftest32.dll
dd if=/dev/zero of=/mnt/w/Windows/System32/winver.exe bs=1k count=4 conv=notrunc
umount /mnt/w
X
}
after_repair_linux() { :; }
check_boot() {
    wait_serial "$1" "WINDOWS-BOOT-OK" 1800 "$2" || return 1
    wait_serial "$1" "WINDOWS-POST-DONE" 7200 "$2" || return 1
    grep -q "WINDOWS-GPU-OK" "$1" && grep -q "WINDOWS-SFC-WINVER=0" "$1" && grep -q "WINDOWS-TESTDLL-PRESENT=False" "$1"
}
