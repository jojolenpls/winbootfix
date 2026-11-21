#!/bin/sh
# Shared helpers for the Windows VM tests (sourced by install.sh and run.sh).
# shellcheck disable=SC2034
set -eu

VM_DIR=${VM_DIR:-$HOME/.cache/winbootfix-vm}
OVMF_CODE_SB=${OVMF_CODE_SB:-/usr/share/OVMF/OVMF_CODE_4M.secboot.fd}
OVMF_CODE=${OVMF_CODE:-/usr/share/OVMF/OVMF_CODE_4M.fd}
OVMF_VARS_MS=${OVMF_VARS_MS:-/usr/share/OVMF/OVMF_VARS_4M.ms.fd}
MEM=${MEM:-4096}
CPUS=${CPUS:-4}

die() { echo "ERROR: $*" >&2; exit 1; }
log() { echo "[$(date +%H:%M:%S)] $*"; }

need() { for c in "$@"; do command -v "$c" >/dev/null || die "missing tool: $c"; done; }

accel() { if [ -w /dev/kvm ]; then echo kvm; else echo tcg; fi; }

# qemu_run NAME DISK VARS SERIAL CODE [extra qemu args...]  (runs in background, prints the pid)
qemu_run() {
    name=$1 disk=$2 vars=$3 serial=$4 code=$5
    shift 5
    tpmdir="$VM_DIR/tpm-$name"
    mkdir -p "$tpmdir"
    swtpm socket --tpmstate dir="$tpmdir" --ctrl type=unixio,path="$tpmdir/sock" --tpm2 --daemon
    qemu-system-x86_64 -name "$name" -machine q35,smm=on,accel="$(accel)" -cpu host -m "$MEM" -smp "$CPUS" \
        -global driver=cfi.pflash01,property=secure,value=on \
        -drive if=pflash,format=raw,unit=0,file="$code",readonly=on \
        -drive if=pflash,format=raw,unit=1,file="$vars" \
        -chardev socket,id=chrtpm,path="$tpmdir/sock" -tpmdev emulator,id=tpm0,chardev=chrtpm \
        -device tpm-tis,tpmdev=tpm0 \
        -drive file="$disk",if=none,id=d0,format=qcow2 -device nvme,drive=d0,serial=wbf0 \
        -device virtio-vga -display none -serial file:"$serial" "$@" &
    echo $!
}

# wait_serial FILE PATTERN TIMEOUT_SECONDS PID
wait_serial() {
    file=$1 pattern=$2 timeout=$3 pid=$4 waited=0
    while ! grep -q "$pattern" "$file" 2>/dev/null; do
        kill -0 "$pid" 2>/dev/null || return 2
        [ "$waited" -ge "$timeout" ] && return 1
        sleep 10
        waited=$((waited + 10))
    done
}

stop_vm() { kill "$1" 2>/dev/null || true; sleep 3; kill -9 "$1" 2>/dev/null || true; }

extract_live_kernel() {
    iso=$1 dest=$2
    mkdir -p "$dest"
    xorriso -osirrox on -indev "$iso" -extract /live/vmlinuz "$dest/vmlinuz" \
        -extract /live/initrd.img "$dest/initrd.img" >/dev/null 2>&1
}

# b64 FILE : base64 on one line, for the kernel command line
b64() { base64 -w0 "$1"; }
