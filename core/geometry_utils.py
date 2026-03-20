"""
Lumina Studio - Geometry Utilities
Geometry utilities module - Pure functional geometry calculation tools
"""

import numpy as np
import trimesh


def create_keychain_loop(width_mm, length_mm, hole_dia_mm, thickness_mm, 
                         attach_x_mm, attach_y_mm):
    """
    Create keychain loop mesh
    
    This is a pure function that generates a rectangle + semicircle loop geometry with hole
    
    Args:
        width_mm: Loop width (millimeters)
        length_mm: Loop length (millimeters)
        hole_dia_mm: Hole diameter (millimeters)
        thickness_mm: Loop thickness (millimeters)
        attach_x_mm: Attachment point X coordinate (millimeters)
        attach_y_mm: Attachment point Y coordinate (millimeters)
    
    Returns:
        trimesh.Trimesh: Loop mesh object
    """
    print(f"[GEOMETRY] Creating keychain loop: w={width_mm}, l={length_mm}, "
          f"hole={hole_dia_mm}, thick={thickness_mm}, pos=({attach_x_mm}, {attach_y_mm})")
    
    # Calculate geometric parameters
    half_w = width_mm / 2
    circle_radius = half_w
    hole_radius = min(hole_dia_mm / 2, circle_radius * 0.8)
    rect_height = max(0.2, length_mm - circle_radius)
    circle_center_y = rect_height
    
    # Generate outer contour points
    n_arc = 32
    outer_pts = []
    
    # Rectangle bottom
    outer_pts.append((-half_w, 0))
    outer_pts.append((half_w, 0))
    outer_pts.append((half_w, rect_height))
    
    # Semicircle top
    for i in range(1, n_arc):
        angle = np.pi * i / n_arc
        x = circle_radius * np.cos(angle)
        y = circle_center_y + circle_radius * np.sin(angle)
        outer_pts.append((x, y))
    
    # Rectangle left side
    outer_pts.append((-half_w, rect_height))
    
    outer_pts = np.array(outer_pts)
    n_outer = len(outer_pts)
    
    # Generate hole points
    n_hole = 32
    hole_pts = []
    for i in range(n_hole):
        angle = 2 * np.pi * i / n_hole
        x = hole_radius * np.cos(angle)
        y = circle_center_y + hole_radius * np.sin(angle)
        hole_pts.append((x, y))
    hole_pts = np.array(hole_pts)
    n_hole_pts = len(hole_pts)
    
    # Build 3D vertices
    vertices = []
    faces = []
    
    # Bottom face outer contour
    for pt in outer_pts:
        vertices.append([pt[0], pt[1], 0])
    
    # Bottom face hole
    for pt in hole_pts:
        vertices.append([pt[0], pt[1], 0])
    
    # Top face outer contour
    for pt in outer_pts:
        vertices.append([pt[0], pt[1], thickness_mm])
    
    # Top face hole
    for pt in hole_pts:
        vertices.append([pt[0], pt[1], thickness_mm])
    
    # Index definitions
    bottom_outer_start = 0
    bottom_hole_start = n_outer
    top_outer_start = n_outer + n_hole_pts
    top_hole_start = n_outer + n_hole_pts + n_outer
    
    # Outer contour side faces
    for i in range(n_outer):
        i_next = (i + 1) % n_outer
        bi = bottom_outer_start + i
        bi_next = bottom_outer_start + i_next
        ti = top_outer_start + i
        ti_next = top_outer_start + i_next
        faces.append([bi, bi_next, ti_next])
        faces.append([bi, ti_next, ti])
    
    # Hole side faces
    for i in range(n_hole_pts):
        i_next = (i + 1) % n_hole_pts
        bi = bottom_hole_start + i
        bi_next = bottom_hole_start + i_next
        ti = top_hole_start + i
        ti_next = top_hole_start + i_next
        faces.append([bi, ti, ti_next])
        faces.append([bi, ti_next, bi_next])
    
    # Connect outer contour and hole (top and bottom faces)
    vertices_arr = np.array(vertices)
    
    bottom_outer_idx = list(range(bottom_outer_start, bottom_outer_start + n_outer))
    bottom_hole_idx = list(range(bottom_hole_start, bottom_hole_start + n_hole_pts))
    bottom_faces = _connect_rings(bottom_outer_idx, bottom_hole_idx, vertices_arr, is_top=False)
    faces.extend(bottom_faces)
    
    top_outer_idx = list(range(top_outer_start, top_outer_start + n_outer))
    top_hole_idx = list(range(top_hole_start, top_hole_start + n_hole_pts))
    top_faces = _connect_rings(top_outer_idx, top_hole_idx, vertices_arr, is_top=True)
    faces.extend(top_faces)
    
    # Apply position offset
    vertices_arr = np.array(vertices)
    vertices_arr[:, 0] += attach_x_mm
    vertices_arr[:, 1] += attach_y_mm
    
    # Create mesh
    mesh = trimesh.Trimesh(vertices=vertices_arr, faces=np.array(faces))
    mesh.fix_normals()
    
    print(f"[GEOMETRY] Loop mesh created: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces")
    
    return mesh


def _connect_rings(outer_indices, hole_indices, vertices_arr, is_top=True):
    """
    Helper function to connect outer ring and inner ring
    Uses greedy algorithm to generate triangular faces
    
    Args:
        outer_indices: Outer ring vertex index list
        hole_indices: Inner ring vertex index list
        vertices_arr: Vertex array
        is_top: Whether it's the top face
    
    Returns:
        list: Face index list
    """
    ring_faces = []
    n_o = len(outer_indices)
    n_h = len(hole_indices)
    
    oi = 0  # Outer ring pointer
    hi = 0  # Inner ring pointer
    
    def get_2d(idx):
        """Get 2D coordinates of vertex"""
        return np.array([vertices_arr[idx][0], vertices_arr[idx][1]])
    
    total_steps = n_o + n_h
    for _ in range(total_steps):
        o_curr = outer_indices[oi % n_o]
        o_next = outer_indices[(oi + 1) % n_o]
        h_curr = hole_indices[hi % n_h]
        h_next = hole_indices[(hi + 1) % n_h]
        
        # Calculate distance to decide connection direction
        dist_o = np.linalg.norm(get_2d(o_next) - get_2d(h_curr))
        dist_h = np.linalg.norm(get_2d(o_curr) - get_2d(h_next))
        
        if oi >= n_o:
            # Outer ring complete, only connect inner ring
            if is_top:
                ring_faces.append([o_curr, h_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, h_next])
            hi += 1
        elif hi >= n_h:
            # Inner ring complete, only connect outer ring
            if is_top:
                ring_faces.append([o_curr, o_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, o_next])
            oi += 1
        elif dist_o < dist_h:
            # Connect next point of outer ring
            if is_top:
                ring_faces.append([o_curr, o_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, o_next])
            oi += 1
        else:
            # Connect next point of inner ring
            if is_top:
                ring_faces.append([o_curr, h_next, h_curr])
            else:
                ring_faces.append([o_curr, h_curr, h_next])
            hi += 1
    
    return ring_faces
