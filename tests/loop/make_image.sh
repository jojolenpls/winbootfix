#!/bin/sh
# Create a GPT disk image like a real Windows PC: ESP (FAT32) + MSR + Windows (NTFS).
# Usage: make_image.sh IMAGE [SIZE_MB]   (needs root: losetup, sgdisk, mkfs.fat, mkntfs)
set -eu
img=${1:?usage: make_image.sh IMAGE [SIZE_MB]}
size=${2:-400}
rm -f "$img"
truncate -s "${size}M" "$img"
sgdisk -o \
  -n 1:2048:+100M -t 1:EF00 -c 1:"EFI system partition" \
  -n 2:0:+16M -t 2:0C01 -c 2:"Microsoft reserved partition" \
  -n 3:0:0 -t 3:0700 -c 3:"Basic data partition" "$img" >/dev/null
dev=$(losetup --show -f -P "$img")
# partitions may need a moment to appear; create the device nodes when udev is absent (containers)
[ -e "/sys/class/block/$(basename "$dev")p3" ] || partx -a "$dev" 2>/dev/null || true
i=0
while [ ! -b "${dev}p3" ] && [ $i -lt 50 ]; do
  for sys in /sys/class/block/"$(basename "$dev")"p*; do
    [ -e "$sys/dev" ] || continue
    node=/dev/$(basename "$sys")
    [ -b "$node" ] || mknod "$node" b "$(cut -d: -f1 "$sys/dev")" "$(cut -d: -f2 "$sys/dev")"
  done
  sleep 0.1; i=$((i+1))
done
mkfs.fat -F 32 -n SYSTEM "${dev}p1" >/dev/null
mkntfs -Q -L Windows "${dev}p3" >/dev/null 2>&1
echo "$dev"
