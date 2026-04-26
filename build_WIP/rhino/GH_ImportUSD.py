import os
import sys
import System
import importlib
import Grasshopper
from System.Collections import IList
from Grasshopper.Kernel.Data import GH_Path

def find_library():
    if "ghenv" in globals():
        try:
            comp = ghenv.Component
            assembly = Grasshopper.Instances.ComponentServer.FindAssembly(comp.ComponentGuid)
            if assembly and assembly.Location:
                plugin_root = os.path.dirname(assembly.Location)
                for root, dirs, files in os.walk(plugin_root):
                    if "ET_rhino.py" in files:
                        return root
        except Exception:
            pass
        
    return ""

library_path = find_library()
if library_path and library_path not in sys.path:
    sys.path.insert(0, library_path)

import ET_rhino
importlib.reload(ET_rhino)

def importusd(Run, Path, Filter):
    if not Filter:
        Filter = "Mesh"
        
    if not Run or not Path or not os.path.exists(Path):
        return None, None, None, None
        
    net_geometry, net_keys, net_domains, net_values = ET_rhino.GH.Import(Path, Filter)
    
    keys_tree = Grasshopper.DataTree[System.String]()
    domains_tree = Grasshopper.DataTree[System.String]()
    values_tree = Grasshopper.DataTree[IList]()
    
    for kvp in net_keys:
        gIdx, kList = kvp.Key, kvp.Value
        keys_tree.AddRange(kList, GH_Path(gIdx))
        
    for kvp in net_domains:
        gIdx, dList = kvp.Key, kvp.Value
        domains_tree.AddRange(dList, GH_Path(gIdx))
        
    for g_kvp in net_values:
        gIdx = g_kvp.Key
        attr_list = g_kvp.Value
        for vList in attr_list:
            values_tree.Add(vList, GH_Path(gIdx))
            
    return net_geometry, keys_tree, domains_tree, values_tree

_run_val = Run if "Run" in globals() else False
_path_val = Path if "Path" in globals() else None
_filter_val = Filter if "Filter" in globals() else None

Geometry, Key, Domain, ValueWrap = importusd(_run_val, _path_val, _filter_val)