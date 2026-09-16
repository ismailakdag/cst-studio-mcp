"""Explicit, bounded modeler acceptance test in an owned new project; no solver.

Refuses a CST session with existing projects. Run only after checking no active solver.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    root = Path(__file__).resolve().parents[1]
    work = root / "build" / ("modeler-" + uuid.uuid4().hex[:10])
    work.mkdir(parents=True)
    records = []
    env = dict(os.environ, CST_CONNECT_MODE="manual", CST_WORK_DIR=str(work), PYTHONPATH=str(root/"src"))
    config = StdioServerParameters(command=sys.executable, args=["-m", "cst_mcp.server"], env=env)
    async with stdio_client(config) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            async def call(name, args):
                response = await asyncio.wait_for(session.call_tool(name, args), timeout=60)
                data = json.loads(response.content[0].text)
                records.append(dict(tool=name, args=args, result=data))
                print(name, data.get("status"), data.get("message", ""), flush=True)
                (work/"validation.json").write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding="utf-8")
                if data.get("status") not in {"ok", "connected", "created", "executed", "saved", "closed", "disconnected", "empty"}:
                    raise RuntimeError(f"{name} failed: {data}")
                return data
            connected = await call("cst_connect", {})
            if connected.get("status") != "connected" or connected.get("open_projects") != 0:
                await call("cst_disconnect", {})
                raise RuntimeError("Acceptance requires an idle CST with zero open projects")
            created = await call("cst_create_project", {"path":str(work/"model.cst")})
            if created.get("status") != "created":
                raise RuntimeError("Could not create isolated project")
            try:
                calls = [
                    ("cst_set_parameter",dict(name="width",value=12.5)),
                    ("cst_get_parameter",dict(name="width")),
                    ("cst_list_parameters",{}),
                    ("cst_create_material",dict(name="TestDielectric",epsilon=4.3,tan_d_e=.025)),
                    ("cst_create_brick",dict(component="test",name="brick",x_min=0,x_max=10,y_min=0,y_max=10,z_min=0,z_max=1.6,material="TestDielectric")),
                    ("cst_create_cylinder",dict(component="test",name="cylinder",axis="z",outer_radius=2,center_x=20,range_min=0,range_max=5)),
                    ("cst_create_sphere",dict(component="test",name="sphere",radius=2,center_x=30)),
                    ("cst_create_wire",dict(component="test",name="wire",radius=.1,start_x=40,start_y=0,start_z=0,end_x=43,end_y=0,end_z=0)),
                    ("cst_create_polygon_extrude",dict(component="test",name="extrude",height=2,points=[[50,0],[52,0],[52,2],[50,2]],axis="z")),
                    ("cst_add_discrete_port",dict(port_number=1,x1=0,y1=0,z1=0,x2=0,y2=0,z2=1.6)),
                    ("cst_add_lumped_element",dict(name="testR",element_type="R",value=50,x1=45,y1=0,z1=0,x2=46,y2=0,z2=0)),
                    ("cst_parameter_sweep",dict(parameter="width",start=12,stop=13,steps=3)),
                    ("cst_optimizer",dict(goal_type="minimize",result_path="1D Results\\S-Parameters\\S1,1",parameters=[dict(name="width",min=12,max=13)],max_evaluations=4)),
                    ("cst_read_project_log",{}),
                    ("cst_save_project",{}),
                ]
                for name,args in calls:
                    await call(name,args)
            finally:
                await call("cst_close_project",{})
                await call("cst_disconnect",{})
    print("Evidence:", work/"validation.json")


if __name__ == "__main__":
    asyncio.run(main())
