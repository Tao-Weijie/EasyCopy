import bpy
import json
import os
from mathutils import Matrix

class BlenderCopy(bpy.types.Operator):
    """Copy selected meshes to clipboard"""
    bl_idname = "object.copy_to_clipboard"
    bl_label = "Copy to Clipboard"
    bl_options = {'REGISTER', 'UNDO'}

    def create_json_data(self, obj):
        mesh = obj.data
        # 1. Vertices
        json_vertices = []
        for i, v in enumerate(mesh.vertices):    
            v_data = {
                "id": i,
                "co": [round(v.co.x, 6), round(v.co.y, 6), round(v.co.z, 6)],
                "tag": "Smooth" # Default
            }
            json_vertices.append(v_data)

        # 2. Edges (Export all edges with tags)
        json_edges = []
        
        # Access custom attribute 'crease_edge' if exists
        crease_data = None
        if "crease_edge" in mesh.attributes:
            att = mesh.attributes["crease_edge"]
            if att.domain == 'EDGE':
                crease_data = att.data
        
        for i, edge in enumerate(mesh.edges):
            v1 = edge.vertices[0]
            v2 = edge.vertices[1]
            
            tag = "Smooth"
            if crease_data and crease_data[i].value > 0.1:
                tag = "Crease"
                
            e_data = {
                "ids": [v1, v2],
                "tag": tag
            }
            json_edges.append(e_data)

        # 3. Faces
        json_faces = []
        for poly in mesh.polygons:
            f_data = {
                "ids": list(poly.vertices)
            }
            json_faces.append(f_data)

        mw = obj.matrix_world
        flat_matrix = [col for row in mw for col in row]
        
        obj_data = {
        "guid": None, 
        "type": "Mesh",
        "software": "Blender",
        "matrix": flat_matrix,
        "vertices": json_vertices,
        "edges": json_edges,
        "faces": json_faces
        }

        return obj_data

    def execute(self, context):
        """Copies selected Mesh objects to JSON format."""
        
        selected_objs = [obj for obj in context.selected_objects if obj.type == 'MESH']
        
        if not selected_objs:
            self.report({'WARNING'}, "No Mesh objects selected.")
            return {'CANCELLED'}

        data_list = []

        for obj in selected_objs:
            obj_data = self.create_json_data(obj)   
            data_list.append(obj_data)

        if not data_list:
             return {'CANCELLED'}

        # Write to File
        try:
            # Mac/Linux/Windows 'Desktop'
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            file_path = os.path.join(desktop, "_temp.json")
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data_list, f, indent=2)
                
            self.report({'INFO'}, f"Copied {len(data_list)} objects")
            
            # Copy to Clipboard
            context.window_manager.clipboard = file_path
            
        except Exception as e:
            self.report({'ERROR'}, f"Error writing file: {e}")
            return {'CANCELLED'}
            
        return {'FINISHED'}


class BlenderPaste(bpy.types.Operator):
    """Paste JSON from Clipboard"""
    bl_idname = "object.easy_paste"
    bl_label = "Paste from Clipboard"
    bl_options = {'REGISTER', 'UNDO'}
        
    def create_object(self, obj_data):
        """Creates a mesh object from data."""
        if "vertices" not in obj_data or "faces" not in obj_data:
            return None

        # 1. Prepare Mesh Data
        verts_loc = []
        json_verts = obj_data.get("vertices", [])
        sorted_verts = sorted(json_verts, key=lambda v: v.get("id", 0))
        
        for v_data in sorted_verts:
            verts_loc.append((v_data["co"][0], v_data["co"][1], v_data["co"][2]))

        faces_indices = [f_data["ids"] for f_data in obj_data["faces"]]

        # 2. Create Mesh
        raw_guid = obj_data.get("guid", "Imported")
        guid = raw_guid or "ImportedObj"
        mesh_name = f"Imported_{guid[:8]}"
        mesh = bpy.data.meshes.new(name=mesh_name)
        mesh.from_pydata(verts_loc, [], faces_indices)
        mesh.polygons.foreach_set("use_smooth", [True] * len(mesh.polygons))
        
        # 3. Apply Creases
        if "edges" in obj_data:
            creased_pairs = set()
            for e_data in obj_data["edges"]:
                tag = e_data.get("tag", "Smooth")
                if tag in ["Crease"]:
                    ids = e_data.get("ids", [])
                    if len(ids) == 2:
                        creased_pairs.add(tuple(sorted((ids[0], ids[1]))))
            
            if creased_pairs:
                try:
                    if "crease_edge" not in mesh.attributes:
                        crease_att = mesh.attributes.new(name="crease_edge", type='FLOAT', domain='EDGE')
                    else:
                        crease_att = mesh.attributes["crease_edge"]
                    
                    values = [0.0] * len(mesh.edges)
                    for i, edge in enumerate(mesh.edges):
                        pair = tuple(sorted((edge.vertices[0], edge.vertices[1])))
                        if pair in creased_pairs:
                            values[i] = 1.0
                    
                    crease_att.data.foreach_set("value", values)
                except Exception as e:
                    print(f"Failed to set crease attribute: {e}")
        
        mesh.update()
        
        # 4. Create Object
        obj = bpy.data.objects.new(mesh_name, mesh)
        bpy.context.collection.objects.link(obj)
        
        # Apply Matrix
        if "matrix" in obj_data and len(obj_data["matrix"]) == 16:
            try:
                m_list = obj_data["matrix"]
                rows = [m_list[i:i+4] for i in range(0, 16, 4)]
                obj.matrix_world = Matrix(rows)
            except Exception as e:
                print(f"Failed to apply matrix: {e}")
        
        # 5. Add Modifier
        mod = obj.modifiers.new(name="Subdivision", type='SUBSURF')
        mod.levels = 3
        mod.render_levels = 3
        
        return obj

    def execute(self, context):
        """Reads file path from clipboard and loads JSON data."""
        try:
            file_path = context.window_manager.clipboard.strip().strip('"')
            
            if not os.path.exists(file_path):
                # Fallback to desktop default if not in clipboard or invalid
                desktop = os.path.join(os.path.expanduser("~"), "Desktop")
                fallback = os.path.join(desktop, "_temp.json")
                if os.path.exists(fallback):
                    file_path = fallback
                else:
                    self.report({'ERROR'}, f"File not found at path: {file_path}")
                    return {'CANCELLED'}
    
            with open(file_path, 'r', encoding='utf-8') as f:
                data_list = json.load(f)
                
            if isinstance(data_list, dict):
                data_list = [data_list]
            elif not isinstance(data_list, list):
                self.report({'ERROR'}, "Invalid JSON structure")
                return {'CANCELLED'}
                
        except Exception as e:
            self.report({'ERROR'}, f"Error reading file: {e}")
            return {'CANCELLED'}
    
        bpy.ops.object.select_all(action='DESELECT')
        
        count = 0
        for obj_data in data_list:
            obj = self.create_object(obj_data)
            if obj:
                obj.select_set(True)
                context.view_layer.objects.active = obj
                count += 1
                
        self.report({'INFO'}, f"Successfully pasted {count} objects.")
        return {'FINISHED'}