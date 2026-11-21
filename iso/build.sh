#!/bin/sh
# Reproducible build of the winbootfix live ISO (Debian 13 "trixie" + live-build).
#
#   With Docker (any Linux):  docker build -t winbootfix-iso iso && \
#                             docker run --rm --privileged -v "$PWD:/src" winbootfix-iso
#   On Debian 13 as root:     apt install live-build make && iso/build.sh
#
# Environment: SNAPSHOT (snapshot.debian.org date, default: iso/SNAPSHOT, "none" = live mirror),
#              SOURCE_DATE_EPOCH (default: last git commit), OUT (default: dist/).
set -eu

here=$(cd "$(dirname "$0")" && pwd)
repo=$(dirname "$here")
out=${OUT:-$repo/dist}
work=${WORK:-$here/build}
SNAPSHOT=${SNAPSHOT:-$(cat "$here/SNAPSHOT")}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$repo" log -1 --format=%ct 2>/dev/null || date +%s)}
export SOURCE_DATE_EPOCH

[ "$(id -u)" = 0 ] || { echo "build.sh must run as root (live-build needs chroot)" >&2; exit 1; }
command -v lb >/dev/null || { echo "live-build is not installed" >&2; exit 1; }

version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$repo/src/winbootfix/__init__.py")
name="winbootfix-$version-amd64"

if [ "$SNAPSHOT" = "none" ]; then
    mirror=http://deb.debian.org/debian/
    security=http://security.debian.org/debian-security/
else
    mirror=http://snapshot.debian.org/archive/debian/$SNAPSHOT/
    security=http://snapshot.debian.org/archive/debian-security/$SNAPSHOT/
fi

rm -rf "$work"
mkdir -p "$work" "$out"
cp -a "$here/config" "$work/config"
make -s -C "$repo" install DESTDIR="$work/config/includes.chroot" PREFIX=/usr
printf '%s\n' "winbootfix $version" "Debian snapshot: $SNAPSHOT" "SOURCE_DATE_EPOCH: $SOURCE_DATE_EPOCH" \
    > "$work/config/includes.chroot/etc/winbootfix-build"

cd "$work"
lb config noauto \
    --mode debian \
    --distribution trixie \
    --archive-areas main \
    --architectures amd64 \
    --linux-flavours amd64 \
    --binary-images iso-hybrid \
    --uefi-secure-boot enable \
    --apt-recommends false \
    --apt-indices false \
    --apt-options "--yes -o Acquire::Check-Valid-Until=false" \
    --debian-installer none \
    --memtest none \
    --firmware-chroot false \
    --firmware-binary false \
    --security true \
    --updates true \
    --mirror-bootstrap "$mirror" \
    --mirror-chroot "$mirror" \
    --mirror-binary "$mirror" \
    --mirror-chroot-security "$security" \
    --mirror-binary-security "$security" \
    --chroot-squashfs-compression-type xz \
    --iso-application "winbootfix $version" \
    --iso-publisher "winbootfix contributors" \
    --iso-volume WINBOOTFIX \
    --bootappend-live "boot=live components quiet locales=C.UTF-8 console=tty0 console=ttyS0,115200n8"

lb build

iso=$(find . -maxdepth 1 -name "*.iso" | sort | head -n1)
[ -n "$iso" ] || { echo "no ISO produced" >&2; exit 1; }
cp "$iso" "$out/$name.iso"
[ -f "$work/chroot.packages.live" ] && cp "$work/chroot.packages.live" "$out/$name.packages"
cd "$out"
sha256sum "$name.iso" > "$name.iso.sha256"
ls -lh "$name.iso"
cat "$name.iso.sha256"
