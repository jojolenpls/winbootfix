#!/bin/sh
# Create the base Windows VM images used by run.sh (unattended install, ~1 hour each).
#   WIN_ISO=Win10_22H2_English_x64.iso tests/vm/install.sh win10-en
#   WIN_ISO=Win11_24H2_French_x64.iso  tests/vm/install.sh win11-fr
# Optional: VIRTIO_ISO=virtio-win.iso (virtio-gpu driver, used by the graphics driver scenario).
set -eu
here=$(cd "$(dirname "$0")" && pwd)
# shellcheck source=/dev/null
. "$here/lib.sh"
name=${1:?usage: install.sh win10-en|win11-fr}
[ -f "$here/autounattend/$name.xml" ] || die "no autounattend for $name"
: "${WIN_ISO:?set WIN_ISO to a Windows 10/11 x64 ISO (evaluation ISOs work)}"
need qemu-system-x86_64 qemu-img swtpm xorriso
mkdir -p "$VM_DIR"

media="$VM_DIR/$name-unattend.iso"
stage=$(mktemp -d)
cp "$here/autounattend/$name.xml" "$stage/autounattend.xml"
cp "$here/guest/report.ps1" "$stage/report.ps1"
xorriso -as mkisofs -quiet -J -r -V UNATTEND -o "$media" "$stage"
rm -rf "$stage"

disk="$VM_DIR/$name.qcow2"
vars="$VM_DIR/$name.vars.fd"
serial="$VM_DIR/$name-install.log"
qemu-img create -f qcow2 "$disk" 64G >/dev/null
cp "$OVMF_VARS_MS" "$vars"
extra="-drive file=$WIN_ISO,media=cdrom,index=1 -drive file=$media,media=cdrom,index=2"
[ -n "${VIRTIO_ISO:-}" ] && extra="$extra -drive file=$VIRTIO_ISO,media=cdrom,index=3"
log "installing $name (this takes a while)..."
# shellcheck disable=SC2086
pid=$(qemu_run "$name" "$disk" "$vars" "$serial" "$OVMF_CODE_SB" $extra -boot d)
if wait_serial "$serial" "WINDOWS-BOOT-OK" 7200 "$pid"; then
    log "installation finished"
else
    stop_vm "$pid"
    die "installation did not finish (see $serial)"
fi
stop_vm "$pid"
log "base image ready: $disk"
