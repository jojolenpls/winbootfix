# shellcheck shell=sh
# Windows + Debian (GRUB first). Remove the Windows entry, repair, check GRUB is untouched and still first.
break_system() {
    cat <<'X'
esp=$(lsblk -rno PATH,PARTTYPE | awk '$2=="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"{print $1; exit}')
mkdir -p /mnt/esp && mount -o ro "$esp" /mnt/esp
(cd /mnt/esp && find EFI/debian EFI/Boot -type f -exec sha256sum {} +) > /run/grub-before.sha
umount /mnt/esp
efibootmgr | sed -n 's/^BootOrder: \([0-9A-F]*\).*/\1/p' > /run/first-before
for n in $(efibootmgr | sed -n 's/^Boot\([0-9A-F]\{4\}\).*Windows Boot Manager.*/\1/p'); do efibootmgr -q -b "$n" -B; done
X
}
after_repair_linux() {
    cat <<'X'
mount -o ro "$esp" /mnt/esp
(cd /mnt/esp && sha256sum -c /run/grub-before.sha) && echo GRUB-FILES-UNCHANGED
umount /mnt/esp
[ "$(efibootmgr | sed -n 's/^BootOrder: \([0-9A-F]*\).*/\1/p')" = "$(cat /run/first-before)" ] && echo GRUB-STILL-FIRST
efibootmgr | grep -q "Windows Boot Manager" && echo WINDOWS-ENTRY-BACK
X
}
# GRUB (Debian, console on ttyS0) must still boot first.
check_boot() {
    grep -q GRUB-FILES-UNCHANGED "$(dirname "$1")/serial-1.log" || return 1
    grep -q GRUB-STILL-FIRST "$(dirname "$1")/serial-1.log" || return 1
    grep -q WINDOWS-ENTRY-BACK "$(dirname "$1")/serial-1.log" || return 1
    wait_serial "$1" "login:" 900 "$2"
}
