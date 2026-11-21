#!/bin/sh
# Boot the ISO in QEMU with OVMF and Secure Boot ON (Microsoft keys enrolled), wait for the
# winbootfix menu marker on the serial console, optionally save a screenshot of the menu.
# Usage: tests/iso/boot_smoke.sh dist/winbootfix-X.Y.Z-amd64.iso [menu.png]
# Needs: qemu-system-x86_64, ovmf, socat, python3.
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

qemu-system-x86_64 -machine q35,smm=on,accel=$accel -m 2048 -smp 2 \
    -global driver=cfi.pflash01,property=secure,value=on \
    -drive if=pflash,format=raw,unit=0,file="$code",readonly=on \
    -drive if=pflash,format=raw,unit=1,file="$work/vars.fd" \
    -cdrom "$iso" -boot d -vga std -display none \
    -serial file:"$work/serial.log" -monitor unix:"$work/mon.sock",server,nowait &
qpid=$!

elapsed=0
while ! grep -q "WINBOOTFIX-MENU-READY" "$work/serial.log" 2>/dev/null; do
    if ! kill -0 "$qpid" 2>/dev/null; then echo "QEMU exited early" >&2; tail -50 "$work/serial.log" >&2; exit 1; fi
    if [ "$elapsed" -ge "$timeout" ]; then echo "timeout: menu not reached" >&2; tail -50 "$work/serial.log" >&2; exit 1; fi
    sleep 5
    elapsed=$((elapsed + 5))
done
echo "OK: winbootfix menu reached after ${elapsed}s (Secure Boot on, accel=$accel)"
grep -i "secure boot" "$work/serial.log" | head -3 || true

if [ -n "$shot" ]; then
    sleep 20
    echo "screendump $work/screen.ppm" | socat - UNIX-CONNECT:"$work/mon.sock" >/dev/null
    sleep 2
    python3 "$here/ppm2png.py" "$work/screen.ppm" "$shot"
    echo "screenshot: $shot"
fi
