from pathlib import Path
import sys, time
sys.path.insert(0, r"E:\CST Studio Suite 2026\AMD64\python_cst_libraries")
import cst.interface as ci

de = ci.DesignEnvironment.connect(22108)
proj_path = r"E:\cstprojects\patch_2p4_retry.cst"

# get open project and close?
p = de.get_open_project(proj_path)
print("open before", de.list_open_projects())
if p is not None:
    try:
        # try save then close
        try:
            p.save()
        except Exception as e:
            print("save", e)
        # Project may have close method
        for meth in ["close", "close_project", "Close"]:
            if hasattr(p, meth):
                print("has", meth)
        # DesignEnvironment may close
        if hasattr(de, "close"):
            pass
        # try p._connection close?
        print([a for a in dir(p) if "close" in a.lower() or "save" in a.lower()])
    except Exception as e:
        print(e)

# reopen
try:
    # if already open, get it; else open
    p2 = de.open_project(proj_path)
    print("reopened", p2)
except Exception as e:
    print("open err", e)
    p2 = de.get_open_project(proj_path) or de.active_project

m3d = p2.model3d
for tree in [
    r"Farfields\farfield (f=2.4) [1]",
    r"Farfields\farfield (f=2.4)",
    r"Farfields",
    r"1D Results\S-Parameters\S1,1",
    r"1D Results\Efficiencies\Rad. Efficiency [1]",
]:
    try:
        print("select", tree, "->", m3d.SelectTreeItem(tree))
    except Exception as e:
        print("select fail", tree, e)

# list tree via simpler VBA
sch = p2.schematic
out = Path(r"E:/cstprojects/exports/tree_dump2.txt")
if out.exists(): out.unlink()
vba = r"""
Sub Main()
Open "E:/cstprojects/exports/tree_dump2.txt" For Output As #1
On Error Resume Next
Dim s As String
s = Resulttree.GetFirstChildName("Farfields")
Print #1, "firstFar=" & s
Dim guard As Long
guard = 0
Do While s <> "" And guard < 30
  Print #1, "F=" & s & " exists=" & CStr(Resulttree.DoesTreeItemExist(s))
  s = Resulttree.GetNextItemName(s)
  guard = guard + 1
Loop
s = Resulttree.GetFirstChildName("1D Results")
guard = 0
Do While s <> "" And guard < 40
  Print #1, "1D=" & s
  s = Resulttree.GetNextItemName(s)
  guard = guard + 1
Loop
Close #1
End Sub
"""
try:
    sch.execute_vba_code(vba)
    print("vba ok")
except Exception as e:
    print("vba", str(e)[-300:])
if out.exists():
    print(out.read_text(encoding="utf-8", errors="replace"))
