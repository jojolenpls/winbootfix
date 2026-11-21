# shellcheck shell=sh
# Delete the "Windows Boot Manager" NVRAM entry.
break_system() {
    cat <<'X'
for n in $(efibootmgr | sed -n 's/^Boot\([0-9A-F]\{4\}\).*Windows Boot Manager.*/\1/p'); do efibootmgr -q -b "$n" -B; done
efibootmgr -v
X
}
after_repair_linux() { echo "efibootmgr -v"; }
check_boot() { wait_serial "$1" "WINDOWS-BOOT-OK" 1800 "$2"; }
