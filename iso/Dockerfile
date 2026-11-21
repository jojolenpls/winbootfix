# Builder image for the winbootfix ISO. Tools come from the same Debian snapshot as the
# ISO content, so a given commit always builds with the same live-build version.
ARG BASE=debian:trixie-slim
FROM ${BASE}
ARG SNAPSHOT=20261115T000000Z
RUN set -eux; \
    rm -f /etc/apt/sources.list.d/debian.sources; \
    echo "deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/${SNAPSHOT}/ trixie main" > /etc/apt/sources.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends live-build debootstrap make git ca-certificates \
        xorriso squashfs-tools mtools dosfstools grub-efi-amd64-bin grub-pc-bin syslinux isolinux syslinux-common; \
    rm -rf /var/lib/apt/lists/*
ENV SNAPSHOT=${SNAPSHOT}
WORKDIR /src
ENTRYPOINT ["/bin/sh", "-c", "git config --global --add safe.directory /src && exec iso/build.sh"]
