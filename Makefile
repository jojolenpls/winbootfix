PREFIX ?= /usr/local
DESTDIR ?=
LIBDIR = $(PREFIX)/lib/winbootfix
SHAREDIR = $(PREFIX)/share/winbootfix
BINDIR = $(PREFIX)/bin
PYTHON ?= python3

.PHONY: install uninstall test test-root lint iso deb windows-zip clean

install:
	install -d $(DESTDIR)$(LIBDIR) $(DESTDIR)$(BINDIR) \
		$(DESTDIR)$(SHAREDIR)/locales $(DESTDIR)$(SHAREDIR)/windows/winpe
	cp -r src/winbootfix $(DESTDIR)$(LIBDIR)/
	find $(DESTDIR)$(LIBDIR) -name __pycache__ -prune -exec rm -rf {} +
	install -m 644 locales/*.json $(DESTDIR)$(SHAREDIR)/locales/
	install -m 644 windows/winbootfix-post.ps1 windows/winbootfix-post.cmd $(DESTDIR)$(SHAREDIR)/windows/
	install -m 644 windows/winpe/build-winpe.ps1 windows/winpe/startnet.cmd windows/winpe/winpe-repair.ps1 \
		$(DESTDIR)$(SHAREDIR)/windows/winpe/
	sed -e 's|@LIBDIR@|$(LIBDIR)|' -e 's|@SHAREDIR@|$(SHAREDIR)|' packaging/winbootfix.in > $(DESTDIR)$(BINDIR)/winbootfix
	chmod 755 $(DESTDIR)$(BINDIR)/winbootfix

uninstall:
	rm -rf $(DESTDIR)$(LIBDIR) $(DESTDIR)$(SHAREDIR) $(DESTDIR)$(BINDIR)/winbootfix

test:
	$(PYTHON) -m pytest -q tests/unit

test-root:
	$(PYTHON) -m pytest -q tests/loop

lint:
	ruff check src tests
	shellcheck install.sh iso/build.sh iso/config/includes.chroot/usr/local/bin/winbootfix-menu \
		iso/config/hooks/normal/*.hook.* tests/loop/make_image.sh tests/iso/*.sh tests/vm/*.sh

iso:
	iso/build.sh

deb:
	packaging/build-deb.sh

windows-zip:
	mkdir -p dist/winbootfix-windows/locales dist/winbootfix-windows/data dist/winbootfix-windows/winpe
	cp windows/winbootfix-post.ps1 windows/winbootfix-post.cmd dist/winbootfix-windows/
	cp windows/winpe/* dist/winbootfix-windows/winpe/
	cp locales/*.json dist/winbootfix-windows/locales/
	cp src/winbootfix/data/gpu.json src/winbootfix/data/dll_db.json dist/winbootfix-windows/data/
	cd dist && rm -f winbootfix-windows.zip && $(PYTHON) -m zipfile -c winbootfix-windows.zip winbootfix-windows

clean:
	rm -rf dist iso/build build *.egg-info
