from pathlib import Path
import sys
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")
import cst.interface as ci

de = ci.DesignEnvironment.connect(22108)
p = de.get_open_project(r"E:\cstprojects\patch_2p4_retry.cst")
m3d = p.model3d
sch = p.schematic

# Python SelectTreeItem
for tree in [
    r"Farfields\farfield (f=2.4) [1]",
    r"Farfields\farfield (f=2.4)",
    r"Farfields",
    r"1D Results\S-Parameters\S1,1",
]:
    try:
        r = m3d.SelectTreeItem(tree)
        print("py select", repr(tree), "->", r)
    except Exception as e:
        print("py select FAIL", tree, e)

# list all tree children under Farfields via VBA Resulttree
out = Path(r"E:/cstprojects/exports/tree_dump.txt")
if out.exists():
    out.unlink()
vba = r"""
Sub Main()
Open "E:/cstprojects/exports/tree_dump.txt" For Output As #1
On Error Resume Next
Dim s As String
s = Resulttree.GetFirstChildName("Farfields")
Print #1, "first=" & s
Dim guard As Long
guard = 0
Do While s <> "" And guard < 50
  Print #1, "item=" & s
  Print #1, "  exists=" & CStr(Resulttree.DoesTreeItemExist(s))
  Print #1, "  type=" & Resulttree.GetItemType(s)
  s = Resulttree.GetNextItemName(s)
  guard = guard + 1
Loop
' also try top-level
Print #1, "--- top ---"
s = Resulttree.GetFirstChildName("")
guard = 0
Do While s <> "" And guard < 40
  Print #1, "top=" & s
  s = Resulttree.GetNextItemName(s)
  guard = guard + 1
Loop
' select tests
Print #1, "sel1=" & CStr(SelectTreeItem("Farfields\farfield (f=2.4) [1]"))
Print #1, "sel2=" & CStr(SelectTreeItem("Farfields\farfield (f=2.4)"))
Print #1, "sel3=" & CStr(SelectTreeItem("1D Results\S-Parameters\S1,1"))
Close #1
End Sub
"""
try:
    sch.execute_vba_code(vba)
    print("vba ok")
except Exception as e:
    print("vba err", str(e)[-400:])
print(out.read_text(encoding="utf-8", errors="replace") if out.exists() else "missing")
