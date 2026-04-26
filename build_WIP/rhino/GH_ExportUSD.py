import os
import sys
import importlib
import Rhino
import System.Drawing
import Eto.Forms
import scriptcontext as sc
from Grasshopper.Kernel.Data import GH_Path
from library import ET_rhino

if "PERSISTENT_MSG" not in globals():
    PERSISTENT_MSG = "Waiting to execute export..."

def exportusd(Run, Path, valid_geo_input, Key, Domain, Value):
    global PERSISTENT_MSG
    if not Run or not Path:
        return PERSISTENT_MSG

    py_geometry = []
    for g in valid_geo_input:
        if "Guid" in str(type(g)):
            rh_obj = Rhino.RhinoDoc.ActiveDoc.Objects.FindId(g)
            if rh_obj: py_geometry.append(rh_obj.Geometry)
        else:
            py_geometry.append(g)
            
    py_names = []
    py_keys = {}
    py_domains = {}
    py_values = {}
    
    for gIdx in range(len(py_geometry)):
        path = GH_Path(gIdx)
        
        if Key and Key.PathExists(path):
            k_list = [str(k) for k in Key.Branch(path)]
        else:
            k_list = []
        py_keys[gIdx] = k_list
            
        if Domain and Domain.PathExists(path):
            d_list = [str(d) for d in Domain.Branch(path)]
        else:
            d_list = []
        py_domains[gIdx] = d_list
            
        v_list = []
        if Value and Value.PathExists(path):
            raw_items = Value.Branch(path)
            for item in raw_items:
                val = getattr(item, "Value", item)
                try:
                    v_list.append(list(val))
                except TypeError:
                    v_list.append([val])
        py_values[gIdx] = v_list

        if not (len(k_list) == len(d_list) == len(v_list)):
            PERSISTENT_MSG = f"Error: Attribute count mismatch at geometry {gIdx}. Keys: {len(k_list)}, Domains: {len(d_list)}, Values: {len(v_list)}."
            return PERSISTENT_MSG
            
    try:
        ET_rhino.GH.Export(Path, py_geometry, py_names, py_keys, py_domains, py_values)
        Eto.Forms.Clipboard.Instance.Text = Path
        PERSISTENT_MSG = f"Successfully exported to {Path}"
        return PERSISTENT_MSG
    except Exception as e:
        PERSISTENT_MSG = f"Export failed: {e}" 
        return PERSISTENT_MSG

class DashedBBoxPreview:
    def __init__(self, comp, box):
        self.comp = comp
        self.box = box
        
    def Draw(self, sender, e):
        try:
            if self.comp is None or self.comp.OnPingDocument() is None:
                Rhino.Display.DisplayPipeline.DrawOverlay -= self.Draw
                return
                
            if getattr(self.comp.Attributes, "Selected", False) and not getattr(self.comp, "Hidden", False):
                color = System.Drawing.Color.Magenta
                
                edges = self.box.GetEdges()
                if edges:
                    for edge in edges:
                        e.Display.DrawPatternedLine(edge.From, edge.To, color, 0x00000F0F, 1)
                        
                if hasattr(e.Display, "DrawBoxCorners"):
                    e.Display.DrawBoxCorners(self.box, color, 2, 2)
        except Exception:
            Rhino.Display.DisplayPipeline.DrawOverlay -= self.Draw

valid_geo_input = []
if Geometry is not None:
    try:
        iter(Geometry)
        valid_geo_input = list(Geometry)
    except TypeError:
        valid_geo_input = [Geometry]

valid_geo_input = [g for g in valid_geo_input if g]

sticky_key = f"usd_export_bbox_{ghenv.Component.InstanceGuid}"
if sticky_key in sc.sticky:
    try:
        old_handler = sc.sticky[sticky_key]
        Rhino.Display.DisplayPipeline.DrawOverlay -= old_handler.Draw
    except Exception:
        pass
    del sc.sticky[sticky_key]

if not valid_geo_input:
    Message = "Warning: Input Geometry is empty."
else:
    bbox = Rhino.Geometry.BoundingBox.Empty
    for g in valid_geo_input:
        b = g.GetBoundingBox(True)
        if b.IsValid:
            bbox.Union(b)
            
    if bbox.IsValid:
        PREVIEW_BBOX_HANDLER = DashedBBoxPreview(ghenv.Component, bbox)
        Rhino.Display.DisplayPipeline.DrawOverlay += PREVIEW_BBOX_HANDLER.Draw
        sc.sticky[sticky_key] = PREVIEW_BBOX_HANDLER

    Message = exportusd(Run, Path, valid_geo_input, Key, Domain, ValueWrap)