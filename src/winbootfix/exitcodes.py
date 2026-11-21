"""Process exit codes. Documented in README (section "Exit codes")."""

OK = 0                  # nothing to do, everything looks fine
ISSUES_FOUND = 1        # problems were found (diagnostic only, nothing changed)
REPAIRED = 2            # every planned repair was applied and verified
PARTIAL = 3             # some repairs failed or were skipped
CANCELLED = 4           # the user declined the confirmation
NOT_ROOT = 10           # must be run as root
NOT_UEFI = 11           # not booted in UEFI mode (or legacy Windows install)
NO_WINDOWS = 12         # no Windows installation found
BITLOCKER_LOCKED = 13   # Windows volume encrypted and no key provided
NO_DISK = 14            # no internal disk visible (VMD / RST / RAID)
UNSUPPORTED_ARCH = 15   # Windows on ARM64 (not supported yet)
NO_BACKUP_TARGET = 16   # no persistent place to store the mandatory backup
USAGE = 64              # bad command line
INTERNAL = 70           # unexpected internal error
