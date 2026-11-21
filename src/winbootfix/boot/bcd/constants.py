"""Well-known BCD object GUIDs, object types and element types. See docs/BCD.md."""

BOOTMGR = "{9dea862c-5cdd-4e70-acc1-f32b344d4795}"
FWBOOTMGR = "{a5a30fa2-3d06-4e9f-b5f4-a01df9d1fcba}"
MEMDIAG = "{b2721d73-1db4-4c62-bf78-c548a880142d}"
GLOBALSETTINGS = "{7ea2e1ac-2e61-4728-aaa3-896d9d0a9f0e}"
BOOTLOADERSETTINGS = "{6efb52bf-1766-41db-a6b3-0ee5eff72bd7}"
RESUMELOADERSETTINGS = "{1afa9c49-16ab-4a5c-901b-212802da9460}"
DBGSETTINGS = "{4636856e-540f-4170-a130-a84776f4c654}"
EMSSETTINGS = "{0ce4991b-e6b3-4b16-b23c-5e0d9250e5d9}"
BADMEMORY = "{5189b25c-5558-4bf2-bca4-289b11bd29e2}"
HYPERVISORSETTINGS = "{7ff607e0-4395-11db-b0de-0800200c9a66}"

# Object types (Objects\{guid}\Description\Type)
TYPE_FW_BOOTMGR = 0x10100001
TYPE_BOOTMGR = 0x10100002
TYPE_OSLOADER = 0x10200003
TYPE_RESUME = 0x10200004
TYPE_MEMDIAG = 0x10200005
TYPE_INHERIT_GLOBAL = 0x20100000
TYPE_INHERIT_OSLOADER = 0x20200003
TYPE_INHERIT_RESUME = 0x20200004

# Element types (Objects\{guid}\Elements\<8 hex digits>\Element)
APP_DEVICE = 0x11000001          # device
APP_PATH = 0x12000002            # string
DESCRIPTION = 0x12000004         # string
LOCALE = 0x12000005              # string
INHERIT = 0x14000006             # object list
RECOVERY_SEQUENCE = 0x14000008   # object list
RECOVERY_ENABLED = 0x16000009    # boolean
ISOLATED_CONTEXT = 0x16000060    # boolean
ALLOWED_INMEMORY = 0x17000077    # integer list
BM_DISPLAY_ORDER = 0x24000001    # object list
BM_DEFAULT = 0x23000003          # object
BM_TIMEOUT = 0x25000004          # integer
BM_RESUME_OBJECT = 0x23000006    # object
BM_TOOLS_ORDER = 0x24000010      # object list
OS_DEVICE = 0x21000001           # device (osloader: osdevice; resume: filedevice)
OS_SYSTEMROOT = 0x22000002       # string (osloader: systemroot; resume: filepath)
OS_RESUME_OBJECT = 0x23000003    # object
OS_NX = 0x25000020               # integer
OS_BOOTMENUPOLICY = 0x250000C2   # integer

# Registry value types used for each element "format" (bits 24-27 of the element type)
FORMAT_DEVICE, FORMAT_STRING, FORMAT_OBJECT, FORMAT_OBJECTLIST = 1, 2, 3, 4
FORMAT_INTEGER, FORMAT_BOOLEAN, FORMAT_INTEGERLIST = 5, 6, 7


def element_format(element_type: int) -> int:
    return (element_type >> 24) & 0xF


def element_key(element_type: int) -> str:
    return f"{element_type:08x}"
