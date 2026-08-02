from pathlib import Path
import re
p = Path(r"E:\CST Studio Suite 2026\Online Help\mergedProjects\VBA_3D\special_vbamonitors\special_vbamonitors_monitor_object.htm")
t = p.read_text(encoding="utf-8", errors="ignore")
methods = re.findall(r'class="VBA-Heading-Method">([^<]+)', t)
print("MONITOR METHODS:")
for m in methods:
    print(" -", m.strip()[:80])
# extract Farfield related text
text = re.sub(r"<[^>]+>", "\n", t)
text = re.sub(r"\n+", "\n", text)
for kw in ["Farfield", "Transient", "ExportFarfield", "Frequency", "Domain", "Create"]:
    print("count", kw, text.count(kw))
# print chunks mentioning Farfield
for m in re.finditer(r".{0,30}[Ff]arfield.{0,200}", text):
    s = m.group(0).replace("\n"," ")
    if len(s) > 40:
        print(">>", s[:250])
