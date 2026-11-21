# shellcheck shell=sh
# Delete the BCD store (exercises the experimental BCD generation, level c).
break_system() {
    cat <<'X'
esp=$(lsblk -rno PATH,PARTTYPE | awk '$2=="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"{print $1; exit}')
mkdir -p /mnt/esp && mount "$esp" /mnt/esp
rm -f /mnt/esp/EFI/Microsoft/Boot/BCD /mnt/esp/EFI/Microsoft/Boot/BCD.LOG*
umount /mnt/esp
X
}
after_repair_linux() { :; }
# Windows must boot with the generated store, then the post-repair script runs bcdboot.
check_boot() { wait_serial "$1" "WINDOWS-BOOT-OK" 1800 "$2" && wait_serial "$1" "WINDOWS-POST-DONE" 7200 "$2"; }
