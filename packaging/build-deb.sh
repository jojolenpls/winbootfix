#!/bin/sh
# Build the .deb from the repository (needs: dpkg-dev, debhelper). Output in dist/.
set -eu
repo=$(cd "$(dirname "$0")/.." && pwd)
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$repo/src/winbootfix/__init__.py")
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
src="$work/winbootfix-$version"
mkdir -p "$src" "$repo/dist"
tar -C "$repo" --exclude=./dist --exclude=./.git --exclude=./iso/build -cf - . | tar -C "$src" -xf -
cp -r "$repo/packaging/debian" "$src/debian"
sed -i "1s/([^)]*)/($version-1)/" "$src/debian/changelog"
(cd "$src" && dpkg-buildpackage -us -uc -b)
mv "$work"/winbootfix_*.deb "$repo/dist/"
ls -l "$repo"/dist/winbootfix_*.deb
