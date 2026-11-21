#!/bin/sh
# Boot the ISO in QEMU with OVMF and Secure Boot ON (Microsoft keys enrolled), wait for the
# winbootfix menu marker on the serial console, optionally save a screenshot of the menu.
# Usage: tests/iso/boot_smoke.sh dist/winbootfix-X.Y.Z-amd64.iso [menu.png]
#   KERNEL_BOOT=1: boot the live kernel directly (no shim/GRUB, Secure Boot off, verbose console):
#                  isolates problems of the live system from problems of the boot chain.
#   FAIL_SHOT=file.png: screenshot saved when the menu is not reached.
# Needs: qemu-system-x86_64, ovmf, socat, python3 (and xorriso for KERNEL_BOOT).
set -eu
iso=${1:?usage: boot_smoke.sh ISO [screenshot.png]}
shot=${2:-}
here=$(cd "$(dirname "$0")" && pwd)
code=${OVMF_CODE:-/usr/share/OVMF/OVMF_CODE_4M.secboot.fd}
vars=${OVMF_VARS:-/usr/share/OVMF/OVMF_VARS_4M.ms.fd}
timeout=${TIMEOUT:-900}
work=$(mktemp -d)
qpid=
cleanup() { [ -n "$qpid" ] && kill "$qpid" 2>/dev/null; rm -rf "$work"; }
trap cleanup EXIT
cp "$vars" "$work/vars.fd"
accel=tcg
[ -w /dev/kvm ] && accel=kvm

set --
if [ "${KERNEL_BOOT:-0}" = 1 ]; then
    code=${OVMF_CODE_PLAIN:-/usr/share/OVMF/OVMF_CODE_4M.fd}
    xorriso -osirrox on -indev "$iso" -extract /live/vmlinuz "$work/vmlinuz" \
        -extract /live/initrd.img "$work/initrd.img" >/dev/null 2>&1
    set -- -kernel "$work/vmlinuz" -initrd "$work/initrd.img" \
        -append "boot=live components console=tty0 console=ttyS0,115200n8 systemd.show_status=1"
fi

qemu-system-x86_64 -machine q35,smm=on,accel=$accel -m 2048 -smp 2 \
    -global driver=cfi.pflash01,property=secure,value=on \
    -drive if=pflash,format=raw,unit=0,file="$code",readonly=on \
    -drive if=pflash,format=raw,unit=1,file="$work/vars.fd" \
    -cdrom "$iso" -boot d -vga std -display none \
    -serial file:"$work/serial.log" -monitor unix:"$work/mon.sock",server,nowait "$@" &
qpid=$!

fail() {
    echo "$1" >&2
    if [ -n "${FAIL_SHOT:-}" ] && kill -0 "$qpid" 2>/dev/null; then
        echo "screendump $work/fail.ppm" | socat - UNIX-CONNECT:"$work/mon.sock" >/dev/null 2>&1 || true
        sleep 2
        [ -f "$work/fail.ppm" ] && python3 "$here/ppm2png.py" "$work/fail.ppm" "$FAIL_SHOT" && echo "screenshot: $FAIL_SHOT" >&2
    fi
    echo "----- serial console (last 120 lines) -----" >&2
    tail -120 "$work/serial.log" >&2 || true
    exit 1
}

elapsed=0
while ! grep -q "WINBOOTFIX-MENU-READY" "$work/serial.log" 2>/dev/null; do
    kill -0 "$qpid" 2>/dev/null || fail "QEMU exited early"
    [ "$elapsed" -ge "$timeout" ] && fail "timeout: menu not reached"
    sleep 5
    elapsed=$((elapsed + 5))
done
mode="Secure Boot on, shim + GRUB"
[ "${KERNEL_BOOT:-0}" = 1 ] && mode="direct kernel boot"
echo "OK: winbootfix menu reached after ${elapsed}s ($mode, accel=$accel)"
grep -i "secure boot" "$work/serial.log" | head -3 || true

if [ -n "$shot" ]; then
    sleep 20
    echo "screendump $work/screen.ppm" | socat - UNIX-CONNECT:"$work/mon.sock" >/dev/null
    sleep 2
    python3 "$here/ppm2png.py" "$work/screen.ppm" "$shot"
    echo "screenshot: $shot"
fi
