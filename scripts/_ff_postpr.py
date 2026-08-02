from pathlib import Path
import re
for path in [
 r"E:\CST Studio Suite 2026\Online Help\mergedProjects\3D\special_postpr\special_postpr_farfield.htm",
 r"E:\CST Studio Suite 2026\Online Help\mergedProjects\3D\special_postpr\special_postpr_pp_farfield.htm",
]:
 p=Path(path)
 print("====", p.name)
 t=p.read_text(encoding="utf-8", errors="ignore")
 text=re.sub(r"<[^>]+>"," ",t)
 text=re.sub(r"\s+"," ",text)
 for kw in ["not available", "unavailable", "HEX", "mesh", "monitor", "frequency"]:
  print(kw, text.lower().count(kw.lower()))
 # print first 2500 chars of cleaned
 print(text[:2500])
 print("---")
