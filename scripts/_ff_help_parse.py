from pathlib import Path
import re
p = Path(r"E:\CST Studio Suite 2026\Online Help\mergedProjects\VBA_3D\special_vbapostproc\special_vbapostproc_farfieldploto.htm")
t = p.read_text(encoding="utf-8", errors="ignore")
methods = re.findall(r'class="VBA-Heading-Method">([^<]+)', t)
print("METHODS:")
for m in methods:
    print(" -", m)
idx = t.find("id=\"Farfield_Results\"")
print("Farfield_Results idx", idx)
if idx > 0:
    chunk = t[idx:idx+10000]
    chunk = re.sub(r"<[^>]+>", "\n", chunk)
    chunk = re.sub(r"\n+", "\n", chunk)
    print(chunk[:5000])
idx2 = t.find("name=\"Examples\"")
print("Examples idx", idx2)
if idx2 > 0:
    chunk = t[idx2:idx2+6000]
    chunk = re.sub(r"<[^>]+>", "\n", chunk)
    chunk = re.sub(r"\n+", "\n", chunk)
    print("EXAMPLE", chunk[:4000])
