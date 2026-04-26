#! python 3
# r: usd-core

import Rhino
import Rhino.DocObjects
import Rhino.ApplicationSettings
import os
import time
import struct
import base64
from System.Drawing import Color
from System import Guid
from Eto.Forms import Clipboard
from pxr import Usd, UsdGeom, Gf, Sdf

USD_TYPE_CONFIG = {
    # === Float32 ===
    'float': ('f', 0), 'half': ('f', 0),
    'float2': ('f', 1), 'texCoord2f': ('f', 1), 'half2': ('f', 1),
    'float3': ('f', 1), 'point3f': ('f', 1), 'vector3f': ('f', 1), 'normal3f': ('f', 1), 'color3f': ('f', 1), 'half3': ('f', 1), 'point3h': ('f', 1), 'normal3h': ('f', 1), 'color3h': ('f', 1),
    'float4': ('f', 1), 'color4f': ('f', 1), 'quatf': ('f', 1), 'half4': ('f', 1), 'texCoord2h': ('f', 1),
    
    # === Float64 ===
    'double': ('d', 0),
    'double2': ('d', 1), 'texCoord2d': ('d', 1),
    'double3': ('d', 1), 'point3d': ('d', 1), 'vector3d': ('d', 1), 'normal3d': ('d', 1), 'color3d': ('d', 1),
    'double4': ('d', 1), 'color4d': ('d', 1), 'quatd': ('d', 1),
    'matrix2d': ('d', 2), 'matrix3d': ('d', 2), 'matrix4d': ('d', 2), 
    
    # === Integers & Booleans ===
    'int': ('i', 0), 'uint': ('I', 0),
    'int2': ('i', 1), 'int3': ('i', 1), 'int4': ('i', 1),
    'int64': ('q', 0), 'uint64': ('Q', 0),
    'bool': ('?', 0)
}

class Attribute:
    """Handles parsing and converting USD Attributes and Primvars."""

    @staticmethod
    def Encode(usd_array, usd_type, function="base64"):
        """Encodes USD array data to a string representation."""
        if function == "base64":
            if not usd_array or len(usd_array) == 0:
                return None

            config = USD_TYPE_CONFIG.get(usd_type)
            if not config:
                print(f"Warning: Unsupported USD type '{usd_type}'")
                return None
            
            fmt_char, flatten_level = config

            try:
                if flatten_level == 0:
                    flat_list = usd_array
                elif flatten_level == 1:
                    flat_list = [val for vec in usd_array for val in vec]
                else:
                    flat_list = [val for mat in usd_array for row in mat for val in row]

                fmt = f"<{len(flat_list)}{fmt_char}"
                packed = struct.pack(fmt, *flat_list)
                return base64.b64encode(packed).decode('ascii')
                
            except Exception as e:
                print(f"Error packing type '{usd_type}': {e}")
                return None
        
        elif function == "string":
            return str(usd_array)
    
    @staticmethod
    def Export(rh_obj, usd_prim):
        """Exports Rhino User Strings to USD Custom userProperties."""
        if not rh_obj: return
        attrs = getattr(rh_obj, "Attributes", None)
        if not attrs: return
        
        user_strings = attrs.GetUserStrings()
        if user_strings:
            for key in user_strings.AllKeys:
                val = attrs.GetUserString(key)
                try:
                    attr_name = f"userProperties:{key}"
                    attr = usd_prim.CreateAttribute(attr_name, Sdf.ValueTypeNames.String)
                    attr.Set(str(val))
                except Exception:
                    pass

    @staticmethod
    def ToUsertext(usd_prim, rh_attrs):
        """
        Reads Custom Attributes and Primvars from USD using ImportAttr and applies them 
        to Rhino ObjectAttributes as User Strings. Native arrays are stored as strings.
        
        Args:
            usd_prim (Usd.Prim): The USD Primitive.
            rh_attrs (list[Rhino.DocObjects.ObjectAttributes]): List of Rhino attributes to apply to.
        """
        import json
        prim_attrs_list = Attribute.ImportAttr(usd_prim)
        
        for base_name, domain, converted_list in prim_attrs_list:
            if not converted_list: continue
            
            key = f"{base_name}:{domain}" if domain else base_name
            
            if domain == "uniform" and len(converted_list) == len(rh_attrs):
                for i, obj_attr in enumerate(rh_attrs):
                    obj_attr.SetUserString(key, str(converted_list[i]))
            elif domain == "constant":
                val_str = str(converted_list[0])
                for obj_attr in rh_attrs:
                    obj_attr.SetUserString(key, val_str)
            else:
                val_str = json.dumps([str(v) for v in converted_list])
                for obj_attr in rh_attrs:
                    obj_attr.SetUserString(key, val_str)

    @staticmethod
    def ImportAttr(usd_prim):
        """
        Extracts USD Custom Attributes and Primvars, converting their contents 
        into flat lists of Rhino.Geometry types or Python primitives. 
        Intended for Grasshopper data bridges.
        
        Args:
            usd_prim (Usd.Prim): The USD Primitive.
            
        Returns:
            list: A list of tuples `(name, domain, data_list)`.
                  `domain` is the interpolation type (e.g. constant, uniform, vertex).
        """

        prim_attrs = []
        
        for attr in usd_prim.GetAuthoredAttributes():
            name = attr.GetName()
            base_name = ""
            domain = ""
            
            # Identifier routing
            if attr.IsCustom() or name.startswith("userProperties:") or name.startswith("primvars:"):
                if name.startswith("userProperties:"):
                    base_name = name.split("userProperties:", 1)[1]
                    domain = "constant"
                elif name.startswith("primvars:"):
                    base_name = attr.GetBaseName()
                    primvar = UsdGeom.Primvar(attr)
                    domain = primvar.GetInterpolation()
                else:
                    base_name = name
                    domain = "constant"
            else:
                continue

            data = attr.Get()
            if data is None:
                continue

            # Ensure data is iterable
            iterable_data = data if hasattr(data, '__iter__') and not isinstance(data, str) else [data]
            converted = []
            
            type_name = attr.GetTypeName().type.typeName
            is_color = "color" in type_name.lower()

            for item in iterable_data:
                t_name = type(item).__name__
                if is_color and ("Vec" in t_name or isinstance(item, (list, tuple))):
                    converted.append(Utility.ToColor4d(item))
                elif t_name in ("Point3f", "Point3d"):
                    converted.append(Utility.ToRhinoPoint3d(item))
                elif t_name in ("Point2f", "Point2d"):
                    converted.append(Utility.ToRhinoPoint2d(item))
                elif t_name in ("Vec3f", "Vec3d", "Normal3f", "Normal3d"):
                    converted.append(Utility.ToRhinoVector3d(item))
                elif t_name in ("Vec2f", "Vec2d"):
                    converted.append(Utility.ToRhinoVector2d(item))
                elif t_name in ("Vec4f", "Vec4d", "Quatf", "Quatd"):
                    converted.append(Utility.ToRhinoPoint4d(item))  # Fallback complex structures to string
                elif isinstance(item, float) or t_name in ('Double', 'Single', 'float'):
                    converted.append(float(item))
                elif isinstance(item, int) or t_name in ('Int32', 'Int64', 'int'):
                    converted.append(int(item))
                elif isinstance(item, bool) or t_name in ('Boolean', 'bool'):
                    converted.append(bool(item))
                elif isinstance(item, str) or t_name in ('String', 'str'):
                    converted.append(str(item))
                else:
                    converted.append(item)

            if converted:
                prim_attrs.append((base_name, domain, converted))

        return prim_attrs

    @staticmethod
    def GetValidName(name):
        """Sanitizes a string to be a valid USD identifier."""
        if not name:
            return None
        valid_name = "".join(c if c.isalnum() or c == '_' else '_' for c in name)
        if valid_name and valid_name[0].isdigit():
            valid_name = "_" + valid_name
        return valid_name

class Export:
    """Handles conversion from Rhino Geometry to USD Prims."""
    @staticmethod
    def Mesh(rh_obj, stage, parent_path, name, mesh_override=None):
        """Converts a Rhino Object's Mesh to a USD Mesh Prim."""
        mesh = mesh_override if mesh_override else rh_obj.Geometry
        mesh_path = f"{parent_path}/{name}"
        usd_mesh = UsdGeom.Mesh.Define(stage, mesh_path)
        
        # Vertices (Topology)
        topo_verts = mesh.TopologyVertices
        points = []
        for i in range(topo_verts.Count):
            points.append(Utility.ToUsdPoint3d(topo_verts[i]))
        usd_mesh.CreatePointsAttr(points)
        
        # Vertex Colors
        if mesh.VertexColors.Count > 0:
            colors = []
            for i in range(topo_verts.Count):
                v_indices = topo_verts.MeshVertexIndices(i)
                if v_indices and len(v_indices) > 0:
                    colors.append(Utility.ToUsdColor3d(mesh.VertexColors[v_indices[0]]))
                else:
                    colors.append(Gf.Vec3d(1.0, 1.0, 1.0))
            color_primvar = UsdGeom.PrimvarsAPI(usd_mesh.GetPrim()).CreatePrimvar(
                "displayColor", Sdf.ValueTypeNames.Color3dArray, UsdGeom.Tokens.vertex
            )
            color_primvar.Set(colors)
        
        def topo_idx(idx): return topo_verts.TopologyVertexIndex(idx)
        
        # Faces
        face_counts = []
        face_indices = []
        processed_faces = set()
        
        # Ngons
        if mesh.Ngons.Count > 0:
            for ngon in mesh.Ngons:
                v_indices = ngon.BoundaryVertexIndexList()
                if v_indices and len(v_indices) > 0:
                    face_counts.append(len(v_indices))
                    topo_indices = [topo_idx(vi) for vi in v_indices]
                    face_indices.extend(topo_indices)
                    f_indices = ngon.FaceIndexList()
                    for f_idx in f_indices:
                        processed_faces.add(f_idx)
        
        # Quads/Tris
        faces = mesh.Faces
        for i in range(faces.Count):
            if i in processed_faces: continue
            f = faces[i]
            if f.IsQuad:
                face_counts.append(4)
                face_indices.extend([topo_idx(f.A), topo_idx(f.B), topo_idx(f.C), topo_idx(f.D)])
            else:
                face_counts.append(3)
                face_indices.extend([topo_idx(f.A), topo_idx(f.B), topo_idx(f.C)])
        
        usd_mesh.CreateFaceVertexCountsAttr(face_counts)
        usd_mesh.CreateFaceVertexIndicesAttr(face_indices)
        
        # Creases
        crease_indices = []
        crease_lengths = []
        crease_sharpnesses = []
        topo_edges = mesh.TopologyEdges
        for i in range(topo_edges.Count):
            connected_faces = topo_edges.GetConnectedFaces(i)
            if len(connected_faces) == 2:
                edge_topo_pair = topo_edges.GetTopologyVertices(i)
                tv1 = edge_topo_pair.I
                tv2 = edge_topo_pair.J
                if topo_edges.IsEdgeUnwelded(i):
                    crease_indices.extend([tv1, tv2])
                    crease_lengths.append(2)
                    crease_sharpnesses.append(10.0) 

        if crease_indices:
            usd_mesh.CreateCreaseIndicesAttr(crease_indices)
            usd_mesh.CreateCreaseLengthsAttr(crease_lengths)
            usd_mesh.CreateCreaseSharpnessesAttr(crease_sharpnesses)
        
        usd_mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.none)
        
        # Extent
        bbox = mesh.GetBoundingBox(True)
        extent = [Utility.ToUsdVec3d(bbox.Min), Utility.ToUsdVec3d(bbox.Max)]
        usd_mesh.CreateExtentAttr(extent)
        
        # Export Attributes
        if rh_obj: Attribute.Export(rh_obj, usd_mesh.GetPrim())
        
        return usd_mesh

    @staticmethod
    def SubD(rh_obj, stage, parent_path, name, geo_override=None):
        """Converts a Rhino Object's SubD to a USD Mesh Prim with Catmull-Clark."""
        subd = geo_override if geo_override else rh_obj.Geometry
        ctrl_mesh = Rhino.Geometry.Mesh.CreateFromSubDControlNet(subd)
        usd_mesh = Export.Mesh(rh_obj, stage, parent_path, name, mesh_override=ctrl_mesh)
        usd_mesh.CreateSubdivisionSchemeAttr(UsdGeom.Tokens.catmullClark)
        if rh_obj: Attribute.Export(rh_obj, usd_mesh.GetPrim())
        return usd_mesh

    @staticmethod
    def PointCloud(rh_obj, stage, parent_path, name, geo_override=None):
        """Converts a Rhino Object's PointCloud to a USD Points Prim."""
        geo = geo_override if geo_override else rh_obj.Geometry
        points_path = f"{parent_path}/{name}"
        usd_points = UsdGeom.Points.Define(stage, points_path)
        
        rh_points = geo.GetPoints()
        points = [Utility.ToUsdPoint3d(p) for p in rh_points]
        usd_points.CreatePointsAttr(points)
        
        if geo.ContainsColors:
            rh_colors = geo.GetColors()
            colors = [Utility.ToUsdColor3d(c) for c in rh_colors]
            usd_points.CreateDisplayColorAttr(colors)
        
        if geo.ContainsNormals:
            rh_normals = geo.GetNormals()
            normals = [Utility.ToUsdVec3d(n) for n in rh_normals]
            usd_points.CreateNormalsAttr(normals)
        
        if geo.ContainsPointValues:
            rh_widths = geo.GetPointValues()
            usd_points.CreateWidthsAttr(rh_widths)
            
        bbox = geo.GetBoundingBox(True)
        extent = [Utility.ToUsdVec3d(bbox.Min), Utility.ToUsdVec3d(bbox.Max)]
        usd_points.CreateExtentAttr(extent)
        
        if rh_obj: Attribute.Export(rh_obj, usd_points.GetPrim())
        return usd_points

    @staticmethod
    def Curve(rh_obj, stage, parent_path, name, geo_override=None):
        """Converts a Rhino Object's Curve to a USD NurbsCurves Prim."""
        geo = geo_override if geo_override else rh_obj.Geometry
        nurbs_curve = geo.ToNurbsCurve()
        if not nurbs_curve: return None
        
        curve_path = f"{parent_path}/{name}"
        usd_curves = UsdGeom.NurbsCurves.Define(stage, curve_path)
        
        points, weights = [], []
        is_rational = nurbs_curve.IsRational
        for p in nurbs_curve.Points:
            points.append(Utility.ToUsdPoint3d(p.Location))
            if is_rational: weights.append(p.Weight)
            
        usd_curves.CreatePointsAttr(points)
        if is_rational: usd_curves.CreatePointWeightsAttr(weights)
            
        usd_curves.CreateCurveVertexCountsAttr([nurbs_curve.Points.Count])
        usd_curves.CreateOrderAttr([nurbs_curve.Order])
        
        rh_knots = list(nurbs_curve.Knots)
        if rh_knots:
            knots = [rh_knots[0]] + rh_knots + [rh_knots[-1]]
            usd_curves.CreateKnotsAttr(knots)
            
        bbox = nurbs_curve.GetBoundingBox(True)
        extent = [Utility.ToUsdVec3d(bbox.Min), Utility.ToUsdVec3d(bbox.Max)]
        usd_curves.CreateExtentAttr(extent)
        
        if rh_obj: Attribute.Export(rh_obj, usd_curves.GetPrim())
        return usd_curves

class Import:
    """Handles conversion from USD Prims to Native Rhino Geometry."""
    @staticmethod
    def Mesh(usd_mesh_geom):
        """Converts a USD Mesh Prim to a Rhino Mesh Object."""
        points_attr = usd_mesh_geom.GetPointsAttr().Get()
        counts_attr = usd_mesh_geom.GetFaceVertexCountsAttr().Get()
        indices_attr = usd_mesh_geom.GetFaceVertexIndicesAttr().Get()
        
        if not points_attr or not counts_attr or not indices_attr: return None
        
        rh_mesh = Rhino.Geometry.Mesh()
        def _parse_perturbed_points(pts):
            """内部方法：通过底层相等性哈希判定重合点，并仅在 Z 轴追加极小随机噪声以防止非流形拓扑融合"""
            import random
            _pts = []
            seen = set()
            for p in pts:
                rh_pt = Utility.ToRhinoPoint3d(p)
                coord = (rh_pt.X, rh_pt.Y, rh_pt.Z)
                if coord in seen:

                    rh_pt.Z += random.uniform(1e-6, 9e-6)
                    seen.add((rh_pt.X, rh_pt.Y, rh_pt.Z))
                else:
                    seen.add(coord)
                _pts.append(rh_pt)
            return _pts
            
        rh_points = _parse_perturbed_points(points_attr)
        rh_mesh.Vertices.AddVertices(rh_points)
        
        # Parse Colors
        color_primvar = UsdGeom.PrimvarsAPI(usd_mesh_geom.GetPrim()).GetPrimvar("displayColor")
        if color_primvar and color_primvar.HasValue():
            interp = color_primvar.GetInterpolation()
            flat_colors = color_primvar.ComputeFlattened()
            rh_colors = []
            if flat_colors:
                if interp == UsdGeom.Tokens.vertex or len(flat_colors) == len(rh_points):
                    rh_colors = [Utility.ToColor4d(c) for c in flat_colors]
                elif interp == UsdGeom.Tokens.faceVarying or len(flat_colors) == len(indices_attr):
                    v_color_dict = {}
                    for face_corner_idx, vertex_idx in enumerate(indices_attr):
                        if vertex_idx not in v_color_dict:
                            v_color_dict[vertex_idx] = Utility.ToColor4d(flat_colors[face_corner_idx])
                    rh_colors = [v_color_dict.get(i, Utility.ToColor4d(Gf.Vec3d(1, 1, 1))) for i in range(len(rh_points))]
                elif interp == UsdGeom.Tokens.constant or len(flat_colors) == 1:
                    c = Utility.ToColor4d(flat_colors[0])
                    rh_colors = [c] * len(rh_points)
                    
            if rh_colors:
                rh_mesh.VertexColors.Clear()
                for c in rh_colors: rh_mesh.VertexColors.Add(c)
        
        # Parse Faces
        mesh_faces = []
        ngon_data = []
        idx_ptr = 0

        for count in counts_attr:
            if count == 3:
                mesh_faces.append(Rhino.Geometry.MeshFace(indices_attr[idx_ptr], indices_attr[idx_ptr + 1], indices_attr[idx_ptr + 2]))
            elif count == 4:
                mesh_faces.append(Rhino.Geometry.MeshFace(indices_attr[idx_ptr], indices_attr[idx_ptr + 1], indices_attr[idx_ptr + 2], indices_attr[idx_ptr + 3]))
            else:
                start_face_idx = len(mesh_faces)
                new_face_indices = []
                v0 = indices_attr[idx_ptr] 
                for i in range(count - 2):
                    mesh_faces.append(Rhino.Geometry.MeshFace(v0, indices_attr[idx_ptr + i + 1], indices_attr[idx_ptr + i + 2]))
                    new_face_indices.append(start_face_idx + i)
                ngon_data.append(new_face_indices)
            idx_ptr += count
        rh_mesh.Faces.AddFaces(mesh_faces)

        # Parse Edges
        topo_verts = rh_mesh.TopologyVertices
        def topo_idx(idx): return topo_verts.TopologyVertexIndex(idx)
            
        crease_indices = usd_mesh_geom.GetCreaseIndicesAttr().Get()
        crease_lengths = usd_mesh_geom.GetCreaseLengthsAttr().Get()
        
        crease_edge = []
        if crease_indices and crease_lengths:
            idx_ptr = 0
            topo_edges = rh_mesh.TopologyEdges
            for length in crease_lengths:
                chain = crease_indices[idx_ptr : idx_ptr + length]
                for i in range(len(chain) - 1):
                    idx1, idx2 = chain[i], chain[i+1]  
                    edge_idx = topo_edges.GetEdgeIndex(topo_idx(idx1), topo_idx(idx2))
                    if edge_idx == -1: edge_idx = topo_edges.GetEdgeIndex(topo_idx(idx2), topo_idx(idx1))
                    if edge_idx != -1: crease_edge.append(edge_idx)
                idx_ptr += length
            rh_mesh.UnweldEdge(crease_edge, False)    

        # Reconstruct Ngons
        if ngon_data:
            ngons = []
            for f_indices in ngon_data:
                v_indices = []
                for i, face_idx in enumerate(f_indices):
                    f = rh_mesh.Faces[face_idx]
                    if i == 0:
                        v_indices.extend([f.A, f.B])
                    elif i == len(f_indices)-1:
                        v_indices.extend([f.B, f.C])
                    else:
                        v_indices.append(f.B)
                    ngon = Rhino.Geometry.MeshNgon.Create(v_indices, f_indices)
                    ngons.append(ngon)
            rh_mesh.Ngons.AddNgons(ngons)

        #rh_mesh.Normals.ComputeNormals()
        #rh_mesh.Compact()
        
        is_valid, log = rh_mesh.IsValidWithLog()
        if not is_valid: print(f"[Warning] Imported Mesh is Invalid: {log}")
        
        xformable = UsdGeom.Xformable(usd_mesh_geom.GetPrim())
        if xformable:
            usd_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            rh_mesh.Transform(Utility.ToRhinoTransform(usd_xform))
        
        return rh_mesh

    @staticmethod
    def SubD(usd_mesh_geom):
        """Converts a USD Mesh Prim (SubD) to a Rhino SubD Object."""
        rh_mesh = Import.Mesh(usd_mesh_geom)
        if not rh_mesh: return None
        rh_subd = Rhino.Geometry.SubD.CreateFromMesh(rh_mesh, Rhino.Geometry.SubDCreationOptions.InteriorCreases)
        if not rh_subd: return None
        return rh_subd

    @staticmethod
    def Points(usd_points_geom):
        """Converts a USD Points Prim to a Rhino PointCloud Object."""
        points_attr = usd_points_geom.GetPointsAttr().Get()
        if not points_attr: return None
            
        rh_pc = Rhino.Geometry.PointCloud()
        rh_points = [Utility.ToRhinoPoint3d(p) for p in points_attr]
        
        normals_attr = usd_points_geom.GetNormalsAttr().Get()
        colors_attr = usd_points_geom.GetDisplayColorAttr().Get()
        width_attr = usd_points_geom.GetWidthsAttr().Get()

        rh_normals = [Utility.ToRhinoVector3d(n) for n in normals_attr] if normals_attr and len(normals_attr) == len(rh_points) else None
        rh_colors = [Utility.ToColor4d(c) for c in colors_attr] if colors_attr and len(colors_attr) == len(rh_points) else None
        rh_widths = [w for w in width_attr] if width_attr and len(width_attr) == len(rh_points) else None
                
        if rh_normals and rh_colors and rh_widths: rh_pc.AddRange(rh_points, rh_normals, rh_colors, rh_widths)
        elif rh_normals and rh_colors: rh_pc.AddRange(rh_points, rh_normals, rh_colors)
        elif rh_normals: rh_pc.AddRange(rh_points, rh_normals)
        elif rh_colors: rh_pc.AddRange(rh_points, rh_colors)
        else: rh_pc.AddRange(rh_points)
             
        xformable = UsdGeom.Xformable(usd_points_geom.GetPrim())
        if xformable:
            usd_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            rh_pc.Transform(Utility.ToRhinoTransform(usd_xform))
            
        return rh_pc

    @staticmethod
    def NurbsCurves(usd_curves_geom):
        """Converts a USD NurbsCurves Prim to a list of Rhino NurbsCurve Objects."""
        counts_attr = usd_curves_geom.GetCurveVertexCountsAttr().Get()
        points_attr = usd_curves_geom.GetPointsAttr().Get()
        order_attr = usd_curves_geom.GetOrderAttr().Get()
        knots_attr = usd_curves_geom.GetKnotsAttr().Get()
        weights_attr = usd_curves_geom.GetPointWeightsAttr().Get()
        
        if not counts_attr or not points_attr or not order_attr or not knots_attr: return []
            
        rh_curves = []
        idx_ptr, knot_ptr = 0, 0
        
        for i, count in enumerate(counts_attr):
            order = order_attr[i] if len(order_attr) > i else order_attr[0]
            is_rational = True if weights_attr else False
            rh_curve = Rhino.Geometry.NurbsCurve(3, is_rational, order, count)
            
            for j in range(count):
                p = points_attr[idx_ptr + j]
                if is_rational:
                    w = weights_attr[idx_ptr + j] if (weights_attr and len(weights_attr) > idx_ptr + j) else 1.0
                    rh_curve.Points.SetPoint(j, Utility.ToRhinoPoint3d(p), w)
                else:
                    rh_curve.Points.SetPoint(j, Utility.ToRhinoPoint3d(p))
            
            if len(knots_attr) >= knot_ptr + count + order:
                for j in range(count + order - 2): rh_curve.Knots[j] = knots_attr[knot_ptr + 1 + j]
                    
            if rh_curve.IsValid: rh_curves.append(rh_curve)
                
            idx_ptr += count
            knot_ptr += count + order
            
        xformable = UsdGeom.Xformable(usd_curves_geom.GetPrim())
        if xformable:
            usd_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            rh_xform = Utility.ToRhinoTransform(usd_xform)
            for crv in rh_curves: crv.Transform(rh_xform)
            
        return rh_curves

    @staticmethod
    def BasisCurves(usd_curves_geom):
        """Converts a USD BasisCurves Prim to a list of Rhino NurbsCurve Objects."""
        counts_attr = usd_curves_geom.GetCurveVertexCountsAttr().Get()
        points_attr = usd_curves_geom.GetPointsAttr().Get()
        prim = usd_curves_geom.GetPrim()
        curve_type = usd_curves_geom.GetTypeAttr().Get() if prim.HasAttribute("curveVertexCounts") else UsdGeom.Tokens.linear
        basis = usd_curves_geom.GetBasisAttr().Get() if prim.HasAttribute("curveVertexCounts") else UsdGeom.Tokens.bezier
        wrap = usd_curves_geom.GetWrapAttr().Get() if prim.HasAttribute("curveVertexCounts") else UsdGeom.Tokens.nonperiodic
        
        if not counts_attr or not points_attr: return []
            
        is_periodic = (wrap == UsdGeom.Tokens.periodic)
        rh_curves = []
        idx_ptr = 0
        
        for count in counts_attr:
            if count == 0: continue
                
            rh_pts = [Utility.ToRhinoPoint3d(points_attr[idx_ptr + j]) for j in range(count)]
            idx_ptr += count 
            
            # Linear Array
            if curve_type == UsdGeom.Tokens.linear:
                if is_periodic and len(rh_pts) > 0 and rh_pts[0].DistanceTo(rh_pts[-1]) > 1e-6: rh_pts.append(rh_pts[0])
                if len(rh_pts) >= 2:
                    plc = Rhino.Geometry.PolylineCurve(Rhino.Geometry.Polyline(rh_pts))
                    if plc and plc.IsValid: rh_curves.append(plc)

            # Cubic Evaluation
            elif curve_type == UsdGeom.Tokens.cubic:
                if basis == UsdGeom.Tokens.bezier:
                    if is_periodic and len(rh_pts) > 0 and len(rh_pts) % 3 == 0: rh_pts.append(rh_pts[0])
                    if len(rh_pts) >= 4 and (len(rh_pts) - 1) % 3 == 0:
                        polycurve = Rhino.Geometry.PolyCurve()
                        for i in range(0, len(rh_pts) - 1, 3):
                            bez = Rhino.Geometry.BezierCurve(rh_pts[i : i+4])
                            polycurve.Append(bez.ToNurbsCurve())
                        if polycurve.IsValid: rh_curves.append(polycurve.ToNurbsCurve())
                elif basis == UsdGeom.Tokens.bspline:
                    nc = Rhino.Geometry.NurbsCurve.Create(False, 3, rh_pts)
                    if nc and nc.IsValid:
                        if is_periodic: nc.MakeClosed(0.001) 
                        rh_curves.append(nc)
                elif basis == UsdGeom.Tokens.catmullRom:
                    if is_periodic and len(rh_pts) > 0 and rh_pts[0].DistanceTo(rh_pts[-1]) > 1e-6: rh_pts.append(rh_pts[0])
                    nc = Rhino.Geometry.Curve.CreateInterpolatedCurve(rh_pts, 3, Rhino.Geometry.CurveKnotStyle.Uniform)
                    if nc and nc.IsValid: rh_curves.append(nc)

        xformable = UsdGeom.Xformable(usd_curves_geom.GetPrim())
        if xformable:
            usd_xform = xformable.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
            rh_xform = Utility.ToRhinoTransform(usd_xform)
            for crv in rh_curves: crv.Transform(rh_xform)

        return rh_curves

class Execute:
    """Main entrypoint for local execution inside Rhino UI."""
    
    @staticmethod
    def GetTempPath():
        home = os.path.expanduser("~")
        return os.path.join(home, "Desktop", "_temp.usda")

    @staticmethod
    def Export():
        start_time = time.time()
        doc_objects = Rhino.RhinoDoc.ActiveDoc.Objects
        rh_objs = list(doc_objects.GetSelectedObjects(False, False))
        if not rh_objs:
            print("No objects selected.")
            return

        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        scale_to_meters = Rhino.RhinoMath.UnitScale(Rhino.RhinoDoc.ActiveDoc.ModelUnitSystem, Rhino.UnitSystem.Meters)
        UsdGeom.SetStageMetersPerUnit(stage, scale_to_meters)
        
        root_path = ""
        count = 0
        used_names = set()
        
        for i, rh_obj in enumerate(rh_objs):           
            geo = rh_obj.Geometry
            raw_name = rh_obj.Attributes.Name
            valid_name = Attribute.GetValidName(raw_name) or f"RhinoObject_{i}"
            
            base_name = valid_name
            dup_count = 1
            while valid_name in used_names:
                valid_name = f"{base_name}_{dup_count}"
                dup_count += 1
            used_names.add(valid_name)
            
            usd_prim = None
            if isinstance(geo, Rhino.Geometry.SubD):
                usd_prim = Export.SubD(rh_obj, stage, root_path, valid_name)
            elif isinstance(geo, Rhino.Geometry.Mesh):
                usd_prim = Export.Mesh(rh_obj, stage, root_path, valid_name)
            elif isinstance(geo, Rhino.Geometry.PointCloud):
                usd_prim = Export.PointCloud(rh_obj, stage, root_path, valid_name)
            elif isinstance(geo, Rhino.Geometry.Curve):
                usd_prim = Export.Curve(rh_obj, stage, root_path, valid_name)
            
            if usd_prim: count += 1

        file_path = Execute.GetTempPath()
        stage.GetRootLayer().Export(file_path)
        
        end_time = time.time()
        print(f"Exported {count} objects to {file_path} in {end_time - start_time:.6f} seconds")
        
        try: Clipboard.Instance.Text = file_path
        except Exception as e: print("Failed to set clipboard:", e)

    @staticmethod
    def Import():
        start_time = time.time()
        file_path = None
        try:
            if Clipboard.Instance.ContainsText: 
                clip_path = Clipboard.Instance.Text.strip().strip('"')
                if os.path.exists(clip_path): file_path = clip_path
        except Exception: pass

        if not file_path:
            print("No valid USD file found in clipboard or desktop.")
            return

        stage = Usd.Stage.Open(file_path)
        if not stage:
            print("Failed to open USD stage.")
            return

        file_meters = UsdGeom.GetStageMetersPerUnit(stage)
        current_meters_factor = Rhino.RhinoMath.UnitScale(Rhino.RhinoDoc.ActiveDoc.ModelUnitSystem, Rhino.UnitSystem.Meters)       
        world_scale = file_meters / current_meters_factor if current_meters_factor > 0 else 1.0

        doc_objects = Rhino.RhinoDoc.ActiveDoc.Objects
        doc_objects.UnselectAll()
        added_ids = []
        
        for prim in stage.Traverse():
            geometries = []
            
            if prim.IsA(UsdGeom.Mesh):
                mesh_geom = UsdGeom.Mesh(prim)
                res = Import.SubD(mesh_geom) if mesh_geom.GetSubdivisionSchemeAttr().Get() == UsdGeom.Tokens.catmullClark else Import.Mesh(mesh_geom)
                if res: geometries.append(res)
            elif prim.IsA(UsdGeom.Points):
                res = Import.Points(UsdGeom.Points(prim))
                if res: geometries.append(res)
            elif prim.IsA(UsdGeom.NurbsCurves):
                geometries.extend(Import.NurbsCurves(UsdGeom.NurbsCurves(prim)))
            elif prim.IsA(UsdGeom.BasisCurves):
                geometries.extend(Import.BasisCurves(UsdGeom.BasisCurves(prim)))
                
            if geometries:
                # Prepare ObjectAttributes Array
                rh_attrs = [Rhino.DocObjects.ObjectAttributes() for _ in geometries]
                Attribute.ToUsertext(prim, rh_attrs)
                
                for geo, attr in zip(geometries, rh_attrs):
                    if world_scale != 1.0: geo.Scale(world_scale)
                    
                    name_str = prim.GetName()
                    if name_str: attr.Name = name_str

                    guid = doc_objects.Add(geo, attr)
                    if guid != Guid.Empty:
                        rh_obj = doc_objects.FindId(guid)
                        if rh_obj:
                            rh_obj.CommitChanges()
                            rh_obj.Select(True)
                            added_ids.append(guid)
            
        end_time = time.time()
        print(f"Imported {len(added_ids)} objects from {file_path} in {end_time - start_time:.6f} seconds")

class GH:
    """Provides pure data USD extraction specifically designed for Grasshopper C# integrations."""

    @staticmethod
    def Import(file_path, filter_type):
        """
        Traverses a USD Stage, filters geometries, and extracts data tree attributes.
        
        Args:
            file_path (str): The absolute path to the USD file.
            filter_type (str): "Mesh", "PointCloud", or "Curve".
            
        Returns:
            tuple: (net_geometry, net_keys, net_attr_data)
        """
        import System
        from System.Collections.Generic import List, Dictionary
        from System.Collections import IList
        import Rhino
        import System.Drawing

        if not file_path or not os.path.exists(file_path):
            return List[System.Object](), Dictionary[System.Int32, List[System.String]](), Dictionary[System.Int32, List[System.String]](), Dictionary[System.Int32, IList]()
        stage = Usd.Stage.Open(file_path)
        if not stage:
            return List[System.Object](), Dictionary[System.Int32, List[System.String]](), Dictionary[System.Int32, List[System.String]](), Dictionary[System.Int32, IList]()

        stage.Reload()
        
        file_meters = UsdGeom.GetStageMetersPerUnit(stage)
        current_meters_factor = Rhino.RhinoMath.UnitScale(Rhino.RhinoDoc.ActiveDoc.ModelUnitSystem, Rhino.UnitSystem.Meters)       
        world_scale = file_meters / current_meters_factor if current_meters_factor > 0 else 1.0
        
        net_geometry = List[System.Object]()
        net_keys = Dictionary[System.Int32, List[System.String]]()
        net_domains = Dictionary[System.Int32, List[System.String]]()
        net_values = Dictionary[System.Int32, IList]()

        usd_prims = [prim for prim in stage.Traverse()]
        py_geometry = []

        for prim in usd_prims:
            geometries = []
            if filter_type == "Mesh" and prim.IsA(UsdGeom.Mesh):
                mesh = Import.Mesh(UsdGeom.Mesh(prim))
                if mesh: geometries.append(mesh)
            elif filter_type == "PointCloud" and prim.IsA(UsdGeom.Points):
                pc = Import.Points(UsdGeom.Points(prim))
                if pc: geometries.append(pc)
            elif filter_type == "Curve":
                if prim.IsA(UsdGeom.NurbsCurves):
                    geometries.extend(Import.NurbsCurves(UsdGeom.NurbsCurves(prim)))
                elif prim.IsA(UsdGeom.BasisCurves):
                    geometries.extend(Import.BasisCurves(UsdGeom.BasisCurves(prim)))

            if geometries:
                if world_scale != 1.0:
                    for geo in geometries: geo.Scale(world_scale)
                    
                start_idx = len(py_geometry)
                py_geometry.extend(geometries)
                
                # Fetch dictionary of plain values for Grasshopper arrays
                prim_attrs_list = Attribute.ImportAttr(prim)

                for offset in range(len(geometries)):
                    g_idx = start_idx + offset
                    
                    net_keys[g_idx] = List[System.String]()
                    net_domains[g_idx] = List[System.String]()
                    net_values[g_idx] = List[IList]()
                    
                    for a_idx, (base_name, domain, converted_list) in enumerate(prim_attrs_list):
                        net_keys[g_idx].Add(base_name)
                        net_domains[g_idx].Add(domain)
                        
                        v_list = Utility.Wrap(converted_list)
                            
                        net_values[g_idx].Add(v_list)

        for g in py_geometry: net_geometry.Add(g)
        
        return net_geometry, net_keys, net_domains, net_values

    @staticmethod
    def Export(file_path, py_geometry, py_names, py_keys, py_domains, py_values):
        """
        Exports native Grasshopper geometries and structured attributes directly to USD.
        """
        if not file_path or not py_geometry: return
        
        stage = Usd.Stage.CreateInMemory()
        UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
        
        try:
            scale_to_meters = Rhino.RhinoMath.UnitScale(Rhino.RhinoDoc.ActiveDoc.ModelUnitSystem, Rhino.UnitSystem.Meters)
            UsdGeom.SetStageMetersPerUnit(stage, scale_to_meters)
        except Exception:
            pass

        root_path = "/Root"
        UsdGeom.Xform.Define(stage, root_path)
        
        for gIdx, geo in enumerate(py_geometry):
            if hasattr(geo, "Value"):
                geo = geo.Value

            name = py_names[gIdx] if py_names and gIdx < len(py_names) and py_names[gIdx] else f"geo_{gIdx}"
            name = Attribute.GetValidName(name)
            
            usd_prim = None
            if isinstance(geo, Rhino.Geometry.Mesh):
                usd_prim = Export.Mesh(None, stage, root_path, name, mesh_override=geo)
            elif isinstance(geo, Rhino.Geometry.PointCloud):
                usd_prim = Export.PointCloud(None, stage, root_path, name, geo_override=geo)
            elif isinstance(geo, Rhino.Geometry.Curve):
                usd_prim = Export.Curve(None, stage, root_path, name, geo_override=geo)
            elif hasattr(Rhino.Geometry, "SubD") and isinstance(geo, Rhino.Geometry.SubD):
                usd_prim = Export.SubD(None, stage, root_path, name, geo_override=geo)
                
            if usd_prim:
                prim = usd_prim.GetPrim()
                keys = py_keys.get(gIdx, [])
                domains = py_domains.get(gIdx, [])
                values = py_values.get(gIdx, [])
                for a_idx, key in enumerate(keys):
                    val_list = values[a_idx]
                    domain = domains[a_idx] 
                    if not val_list: continue
                    
                    try:
                        valid_key = str(key)
                        test_v = val_list[0]
                        
                        # 兼容 Grasshopper 原生 Goo 包装类型拆包
                        if hasattr(test_v, "Value"):
                            test_v = test_v.Value
                            
                        t_name = type(test_v).__name__
                        
                        if isinstance(test_v, bool) or t_name == 'Boolean':
                            usd_type = Sdf.ValueTypeNames.BoolArray
                            v_array = [bool(v) for v in val_list]
                        elif isinstance(test_v, int) or t_name in ['Int32', 'Int64']:
                            usd_type = Sdf.ValueTypeNames.IntArray
                            v_array = [int(v) for v in val_list]
                        elif isinstance(test_v, float) or t_name in ['Double', 'Single']:
                            usd_type = Sdf.ValueTypeNames.DoubleArray
                            v_array = [float(v) for v in val_list]
                        elif t_name == 'Color' or 'Color' in str(type(test_v)):
                            usd_type = Sdf.ValueTypeNames.Color4dArray
                            v_array = [Utility.ToUsdColor4d(v) for v in val_list]
                        elif isinstance(test_v, Rhino.Geometry.Point3d) or t_name == 'Point3d':
                            usd_type = Sdf.ValueTypeNames.Point3dArray
                            v_array = [Utility.ToUsdPoint3d(v) for v in val_list]
                        elif isinstance(test_v, Rhino.Geometry.Point4d) or t_name == 'Point4d':
                            usd_type = Sdf.ValueTypeNames.Point4dArray
                            v_array = [Utility.ToUsdPoint4d(v) for v in val_list]
                        elif isinstance(test_v, Rhino.Geometry.Vector3d) or t_name == 'Vector3d':
                            usd_type = Sdf.ValueTypeNames.Vector3dArray
                            v_array = [Utility.ToUsdVec3d(v) for v in val_list]
                        else:
                            usd_type = Sdf.ValueTypeNames.StringArray
                            v_array = [str(v) for v in val_list]
                            
                        # 核心写入：区分 User Property 和 Primvar
                        if valid_key.startswith("userProperties:"):
                            attr = prim.CreateAttribute(valid_key, usd_type)
                            attr.Set(v_array)
                        else:
                            pv = UsdGeom.PrimvarsAPI(prim).CreatePrimvar(valid_key, usd_type, domain)
                            pv.Set(v_array)
                    except Exception as e:
                        print(f"[Warning] Failed to export GH attribute {key} on {name}: {e}")
                            
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
            stage.GetRootLayer().Export(file_path)
        except Exception as e:
            print(f"Error exporting USD to file {file_path}: {e}")

class Utility:
    # ==========================================
    #             Python <-> C# List Wrapping
    # ==========================================
    
    @staticmethod
    def Wrap(python_list):
        """Converts a pure Python list into a strongly-typed .NET System.Collections.Generic.List."""
        import System
        from System.Collections.Generic import List
        import System.Drawing
        import Rhino
        
        if not python_list or len(python_list) == 0:
            return List[System.Object]()
            
        first_item = python_list[0]
        t_name = type(first_item).__name__
        
        try:
            if isinstance(first_item, bool) or t_name == 'Boolean':
                v_list = List[bool]()
            elif isinstance(first_item, int) or t_name in ['Int32', 'Int64']:
                v_list = List[int]()
            elif isinstance(first_item, float) or t_name in ['Double', 'Single']:
                v_list = List[float]()
            elif isinstance(first_item, str) or t_name == 'String':
                v_list = List[str]()
            elif t_name == 'Color' or 'Color' in str(type(first_item)):                           
                v_list = List[System.Drawing.Color]()
            elif isinstance(first_item, Rhino.Geometry.Point3d) or t_name == 'Point3d':
                v_list = List[Rhino.Geometry.Point3d]()
            elif isinstance(first_item, Rhino.Geometry.Point4d) or t_name == 'Point4d':
                v_list = List[Rhino.Geometry.Point4d]()
            elif isinstance(first_item, Rhino.Geometry.Vector3d) or t_name == 'Vector3d':
                v_list = List[Rhino.Geometry.Vector3d]()
            else:
                raise TypeError(f"Cannot convert value type '{t_name}' to any supported Rhino/GH data type.")
                
            for v in python_list: v_list.Add(v)
            return v_list
        except Exception as e:
            raise TypeError(f"Error occurred while boxing to typed list, conversion failed. Details: {e}")

    # ==========================================
    #             USD -> Rhino
    # ==========================================
    @staticmethod
    def ToRhinoTransform(gf_mat):
        xform = Rhino.Geometry.Transform()
        xform.M00 = gf_mat[0][0]; xform.M01 = gf_mat[1][0]; xform.M02 = gf_mat[2][0]; xform.M03 = gf_mat[3][0]
        xform.M10 = gf_mat[0][1]; xform.M11 = gf_mat[1][1]; xform.M12 = gf_mat[2][1]; xform.M13 = gf_mat[3][1]
        xform.M20 = gf_mat[0][2]; xform.M21 = gf_mat[1][2]; xform.M22 = gf_mat[2][2]; xform.M23 = gf_mat[3][2]
        xform.M30 = gf_mat[0][3]; xform.M31 = gf_mat[1][3]; xform.M32 = gf_mat[2][3]; xform.M33 = gf_mat[3][3]
        return xform

    @staticmethod
    def ToRhinoPoint2d(gf_pt):
        return Rhino.Geometry.Point3d(gf_pt[0], gf_pt[1], 0)

    
    @staticmethod
    def ToRhinoPoint3d(gf_pt):
        return Rhino.Geometry.Point3d(gf_pt[0], gf_pt[1], gf_pt[2])

    @staticmethod
    def ToRhinoPoint4d(gf_pt):
        return Rhino.Geometry.Point4d(gf_pt[0], gf_pt[1], gf_pt[2], gf_pt[3])
    
    @staticmethod
    def ToRhinoVector2d(gf_vec):
        return Rhino.Geometry.Vector3d(gf_vec[0], gf_vec[1], 0)
    
    @staticmethod
    def ToRhinoVector3d(gf_vec):
        return Rhino.Geometry.Vector3d(gf_vec[0], gf_vec[1], gf_vec[2])

    @staticmethod
    def ToColor4d(gf_color):
        r = int(max(0.0, min(1.0, gf_color[0])) * 255)
        g = int(max(0.0, min(1.0, gf_color[1])) * 255)
        b = int(max(0.0, min(1.0, gf_color[2])) * 255)
        if len(gf_color) == 4:
            a = int(max(0.0, min(1.0, gf_color[3])) * 255)
        else:
            a = 255
        return Color.FromArgb(a, r, g, b)

    # ==========================================
    #             Rhino -> USD
    # ==========================================

    @staticmethod
    def ToUsdPoint4d(rh_pt):
        return Gf.Vec4d(rh_pt.X, rh_pt.Y, rh_pt.Z, rh_pt.W)
    
    @staticmethod
    def ToUsdPoint3d(rh_pt):
        return Gf.Vec3d(rh_pt.X, rh_pt.Y, rh_pt.Z)
    
    @staticmethod
    def ToUsdPoint2d(rh_pt):
        return Gf.Vec2d(rh_pt.X, rh_pt.Y)
    
    @staticmethod
    def ToUsdVec3d(rh_vec):
        return Gf.Vec3d(rh_vec.X, rh_vec.Y, rh_vec.Z)

    @staticmethod
    def ToUsdVec2d(rh_pt_or_vec):
        return Gf.Vec2d(rh_pt_or_vec.X, rh_pt_or_vec.Y)

    @staticmethod
    def ToUsdColor3d(rh_color):
        return Gf.Vec3d(rh_color.R / 255.0, rh_color.G / 255.0, rh_color.B / 255.0)

    @staticmethod
    def ToUsdColor4d(rh_color):
        return Gf.Vec4d(rh_color.R / 255.0, rh_color.G / 255.0, rh_color.B / 255.0, rh_color.A / 255.0)
