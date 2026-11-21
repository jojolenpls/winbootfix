# shellcheck shell=sh
# Delete the NVRAM entry and every Windows boot file except the BCD.
break_system() {
    cat <<'X'
for n in $(efibootmgr | sed -n 's/^Boot\([0-9A-F]\{4\}\).*Windows Boot Manager.*/\1/p'); do efibootmgr -q -b "$n" -B; done
esp=$(lsblk -rno PATH,PARTTYPE | awk '$2=="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"{print $1; exit}')
mkdir -p /mnt/esp && mount "$esp" /mnt/esp
find /mnt/esp/EFI/Microsoft/Boot -type f ! -name BCD -delete
rm -f /mnt/esp/EFI/Boot/bootx64.efi
umount /mnt/esp
X
}
after_repair_linux() { :; }
check_boot() { wait_serial "$1" "WINDOWS-BOOT-OK" 1800 "$2"; }
