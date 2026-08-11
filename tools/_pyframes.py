import re
from collections import Counter
data = open(r"C:\Users\matve\AppData\Local\CrashDumps\Unlock.exe.18996.dmp", "rb").read()
c = Counter()
for m in re.finditer(rb"[a-z_]+\.py", data):
    c[m.group()] += 1
for k, v in c.most_common(60):
    print(v, k.decode())
