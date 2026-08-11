import sys, struct
from minidump.minidumpfile import MinidumpFile

path = r"C:\Users\matve\AppData\Local\CrashDumps\Unlock.exe.18996.dmp"
md = MinidumpFile.parse(path)

exc = md.exception.exception_records[0]
tid = exc.ThreadId
code = exc.ExceptionRecord.ExceptionCode_raw
print("crashing tid:", tid, "code:", hex(code), "addr:", hex(exc.ExceptionRecord.ExceptionAddress))

mods = []
for m in md.modules.modules:
    mods.append((m.baseaddress, m.endaddress, m.name))
mods.sort()

def lookup(addr):
    for base, end, name in mods:
        if base <= addr < end:
            return name, addr - base
    return None, None

thread = None
for t in md.threads.threads:
    if t.ThreadId == tid:
        thread = t
        break
if thread is None:
    print("thread not found"); sys.exit(1)

ctxf = open(path, "rb")
ctxf.seek(exc.ThreadContext.Rva)
cdata = ctxf.read(0x100)
rip = struct.unpack_from("<Q", cdata, 0xF8)[0]
rsp = struct.unpack_from("<Q", cdata, 0x98)[0]
rbp = struct.unpack_from("<Q", cdata, 0xA0)[0]
print("RIP=%x RSP=%x RBP=%x" % (rip, rsp, rbp))
mod, off = lookup(rip)
print("RIP in:", mod, hex(off) if off is not None else "")

rva = thread.Stack.Rva
size = thread.Stack.DataSize
f = open(path, "rb"); f.seek(rva); data = f.read(size); f.close()

stack_base = thread.Stack.StartOfMemoryRange
print("stack size:", size)

seen = set()
count = 0
for i in range(0, size - 8, 8):
    val = struct.unpack_from("<Q", data, i)[0]
    name, off = lookup(val)
    if name is None:
        continue
    key = (name.split("\\")[-1], off)
    if key in seen:
        continue
    seen.add(key)
    print("rsp+%05x -> %s + 0x%x" % (i, name.split("\\")[-1], off))
    count += 1
    if count > 60:
        break
