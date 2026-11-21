#!/bin/sh
# winbootfix one-line installer for Linux:
#   curl -fsSL https://raw.githubusercontent.com/jojolenpls/winbootfix/main/install.sh | sudo sh
# Options (after "sh -s --"): --version vX.Y.Z   --prefix /usr/local   --uninstall
set -eu

REPO="jojolenpls/winbootfix"
PREFIX=/usr/local
VERSION=latest
ACTION=install

while [ $# -gt 0 ]; do
    case "$1" in
        --version) VERSION=$2; shift 2 ;;
        --prefix) PREFIX=$2; shift 2 ;;
        --uninstall) ACTION=uninstall; shift ;;
        -h|--help) sed -n '2,4p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 64 ;;
    esac
done

[ "$(id -u)" = 0 ] || { echo "Run as root (sudo)." >&2; exit 10; }

if [ "$ACTION" = uninstall ]; then
    rm -rf "$PREFIX/lib/winbootfix" "$PREFIX/share/winbootfix" "$PREFIX/bin/winbootfix"
    echo "winbootfix removed."
    exit 0
fi

install_deps() {
    if command -v apt-get >/dev/null; then
        apt-get update -qq
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3 python3-hivex efibootmgr ntfs-3g \
            dosfstools whiptail make curl ca-certificates
    elif command -v dnf >/dev/null; then
        dnf install -y python3 python3-hivex efibootmgr ntfs-3g dosfstools newt make curl
    elif command -v pacman >/dev/null; then
        pacman -Sy --needed --noconfirm python hivex efibootmgr ntfs-3g dosfstools libnewt make curl
    elif command -v zypper >/dev/null; then
        zypper --non-interactive install python3 python3-hivex efibootmgr ntfs-3g dosfstools newt make curl
    else
        echo "Unknown package manager: install python3, hivex (python bindings), efibootmgr, ntfs-3g yourself." >&2
    fi
}

install_deps

if [ "$VERSION" = latest ]; then
    base="https://github.com/$REPO/releases/latest/download"
else
    base="https://github.com/$REPO/releases/download/$VERSION"
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
echo "Downloading winbootfix ($VERSION)..."
curl -fsSL "$base/winbootfix-src.tar.gz" -o "$tmp/winbootfix-src.tar.gz"
curl -fsSL "$base/winbootfix-src.tar.gz.sha256" -o "$tmp/winbootfix-src.tar.gz.sha256"
(cd "$tmp" && sha256sum -c winbootfix-src.tar.gz.sha256)
mkdir "$tmp/src"
tar -xzf "$tmp/winbootfix-src.tar.gz" -C "$tmp/src" --strip-components=1
make -C "$tmp/src" install PREFIX="$PREFIX"
echo
echo "Installed. Diagnose (changes nothing):   sudo winbootfix"
echo "Diagnose and repair:                     sudo winbootfix --apply"
