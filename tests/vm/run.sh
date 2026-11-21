#!/bin/sh
# Run the repair scenarios against a base image made by install.sh.
#   ISO=dist/winbootfix-0.1.0-amd64.iso tests/vm/run.sh win10-en nvram efifiles bcd health
#   ISO=... tests/vm/run.sh dual dualboot      (base image "dual": Windows + Debian, see dualboot/README.md)
# Each scenario: 1) boot the winbootfix ISO, break something, repair with winbootfix --apply --yes;
#                2) boot the disk and wait for Windows (serial markers written by guest/report.ps1).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=/dev/null
. "$here/lib.sh"
base=${1:?usage: run.sh BASE SCENARIO...}
shift
: "${ISO:?set ISO to the winbootfix ISO}"
need qemu-system-x86_64 qemu-img swtpm xorriso base64
kdir="$VM_DIR/kernel"
extract_live_kernel "$ISO" "$kdir"
failed=0

for scenario in "$@"; do
    sfile="$here/scenarios/$scenario.sh"
    [ -f "$sfile" ] || die "unknown scenario $scenario"
    work="$VM_DIR/run-$base-$scenario"
    rm -rf "$work"
    mkdir -p "$work"
    qemu-img create -f qcow2 -b "$VM_DIR/$base.qcow2" -F qcow2 "$work/disk.qcow2" >/dev/null
    cp "$VM_DIR/$base.vars.fd" "$work/vars.fd"
    cp -r "$VM_DIR/tpm-$base" "$VM_DIR/tpm-$base-$scenario" 2>/dev/null || true

    # shellcheck source=/dev/null
    . "$sfile"
    {
        echo "set -x"
        break_system
        echo "export WINBOOTFIX_POST_EXTRA_ARGS='-Yes -NoPause'"
        echo "winbootfix --apply --yes --lang en --allow-volatile-backup --report-dir /run/wbf; echo WBF-RC=\$?"
        echo "cat /run/wbf/*.txt"
        after_repair_linux
    } > "$work/autorun.sh"

    log "[$scenario] phase 1: break + repair from the winbootfix ISO"
    pid=$(qemu_run "$base-$scenario" "$work/disk.qcow2" "$work/vars.fd" "$work/serial-1.log" "$OVMF_CODE" \
        -drive file="$ISO",media=cdrom -kernel "$kdir/vmlinuz" -initrd "$kdir/initrd.img" \
        -append "boot=live components quiet console=ttyS0,115200 winbootfix.test=1 winbootfix.autorun=$(b64 "$work/autorun.sh")")
    if ! wait_serial "$work/serial-1.log" "WINBOOTFIX-AUTORUN-EXIT=" 1800 "$pid"; then
        log "[$scenario] FAIL: winbootfix did not finish"; failed=1; stop_vm "$pid"; continue
    fi
    stop_vm "$pid"
    grep -q "WBF-RC=2" "$work/serial-1.log" || { log "[$scenario] FAIL: repair exit code"; grep WBF-RC "$work/serial-1.log"; failed=1; continue; }

    log "[$scenario] phase 2: boot the disk"
    pid=$(qemu_run "$base-$scenario" "$work/disk.qcow2" "$work/vars.fd" "$work/serial-2.log" "$OVMF_CODE_SB")
    if check_boot "$work/serial-2.log" "$pid"; then
        log "[$scenario] PASS"
    else
        log "[$scenario] FAIL (see $work/serial-2.log)"; failed=1
    fi
    stop_vm "$pid"
done
exit $failed
