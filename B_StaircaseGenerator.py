import bpy
import math
from mathutils import Vector

# Clear old stairs
#def delete_old_stairs():
#   for obj in bpy.data.objects:
#        if obj.get("is_stair"):
#            bpy.data.objects.remove(obj, do_unlink=True)

# Create a single step
def create_step(location, size, name):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    step = bpy.context.active_object
    step.name = name
    step.scale = Vector(size)  # (width/2, depth/2, height/2)
    step["is_stair"] = True
    return step

# Create a landing platform
def create_landing(location, size, name):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    landing = bpy.context.active_object
    landing.name = name
    landing.scale = Vector(size)
    landing["is_stair"] = True
    return landing

# Draw linear staircase with landing at the top
def create_linear_stairs(props):
    # Create steps
    for i in range(props.step_count):
        location = Vector((
            0,
            i * props.step_depth,
            i * props.step_height
        ))
        create_step(location, (props.step_width, props.step_depth, props.step_height), f"Step_{i}")
    
    # Create top landing
    if props.add_landing:
        last_step_y = (props.step_count - 1)* props.step_depth
        last_step_z = (props.step_count) * props.step_height
        
        landing_y = last_step_y + props.step_depth / 2 + props.landing_depth / 2
        landing_z = last_step_z + props.step_height / 2 - props.step_height / 2  # same as last step top center
        
        landing_location = Vector((
            0,
            landing_y,
            landing_z
        ))
        create_landing(landing_location, (props.step_width, props.landing_depth, props.step_height), "Landing_Top")

# Draw L-Shape staircase with intermediate and top landings
def create_l_shape_stairs(props):
    first_run_count = props.l_first_run_count
    second_run_count = props.l_second_run_count
    
    # First run (along Y-axis)
    for i in range(first_run_count):
        location = Vector((0, i * props.step_depth, i * props.step_height))
        create_step(location, (props.step_width, props.step_depth, props.step_height), f"Step_L1_{i}")
    
    # Intermediate landing at the corner - positioned to connect with last step of first run
    if props.add_landing:
        last_step_y = (first_run_count - 1) * props.step_depth
        last_step_z = first_run_count * props.step_height

        landing_y = last_step_y + props.step_depth / 2 + props.landing_depth / 2
        landing_z = last_step_z + props.step_height / 2 - props.step_height / 2  # same as last step top center

        corner_landing_location = Vector((0, landing_y, landing_z))
        create_landing(corner_landing_location, (props.landing_depth, props.landing_depth, props.step_height), "Landing_Corner")
    
    # Second run (along X-axis) - starts from the edge of corner landing
    landing_offset = props.landing_depth if props.add_landing else 0
    for j in range(second_run_count):
        location = Vector((
            (landing_offset + (j + 1)) * props.step_depth,
            (first_run_count - 1) * props.step_depth + props.step_depth / 2 + landing_offset / 2,
            (first_run_count + j + 1) * props.step_height
        ))
        create_step(location, (props.step_depth, props.step_width, props.step_height), f"Step_L2_{j}")
    
    # Top landing - positioned at the end of second run
    if props.add_landing:
        top_landing_location = Vector((
            landing_offset + (second_run_count - 1) * props.step_depth + props.landing_depth / 4,
            (first_run_count - 1 ) * props.step_depth + props.step_depth / 2 + landing_offset / 2,
            (first_run_count + second_run_count + props.landing_depth ) * props.step_height
        ))
        create_landing(top_landing_location, (props.landing_depth, props.step_width, props.step_height), "Landing_Top")

# Draw U-Shape staircase with 2 runs and landings
def create_u_shape_stairs(props):
    first_run_count = props.u_first_run_count
    second_run_count = props.u_second_run_count
    
    # First run (along +Y direction)
    for i in range(first_run_count):
        location = Vector((0, i * props.step_depth, i * props.step_height))
        create_step(location, (props.step_width, props.step_depth, props.step_height), f"Step_U1_{i}")
    
    # Intermediate landing at the turn - positioned to connect with last step of first run
    if props.add_landing:
        last_step_y = first_run_count  * props.step_depth - props.step_depth/2
        last_step_z = first_run_count * props.step_height
        
        landing_width = props.step_width + props.landing_depth
        landing_depth = props.step_depth + props.landing_depth
        
        landing_x = landing_width - props.step_width  
        landing_y = last_step_y + props.step_depth / 2 + props.landing_depth / 3
        landing_z = last_step_z + props.step_height / 2 - props.step_height / 2  # same as last step top center
        
        
        mid_landing_location = Vector((landing_x ,landing_y, landing_z ))
        
            #props.step_width / 2 + props.landing_depth / 2,
            #(first_run_count - 1) * props.step_depth + props.step_depth / 2,
            #first_run_count * props.step_height
        
        create_landing(mid_landing_location, (props.landing_depth  , props.landing_depth  , props.step_height), "Landing_Mid")
    
        # Intermediate landing at the corner - positioned to connect with last step of first run
    if props.add_landing:
        last_step_y = (first_run_count - 1) * props.step_depth
        last_step_z = first_run_count * props.step_height

        landing_y = last_step_y + props.step_depth / 2 + props.landing_depth / 2
        landing_z = last_step_z + props.step_height / 2 - props.step_height / 2  # same as last step top center

        corner_landing_location = Vector((0, landing_y, landing_z))
        create_landing(corner_landing_location, (props.landing_depth, props.landing_depth, props.step_height), "Landing_Corner")
    
    
    # Second run (along -Y direction, offset in X) - starts from the edge of mid landing
    x_offset = props.landing_depth if props.add_landing else 0
    for j in range(second_run_count):
        location = Vector((
            x_offset,
            (first_run_count - props.step_width/2 ) * props.step_depth + props.step_depth / 2 - (j + 1) * props.step_depth,
            (first_run_count + j) * props.step_height + props.step_height
        ))
        create_step(location, (props.step_width, props.step_depth, props.step_height), f"Step_U2_{j}")
    
    # Top landing - positioned at the end of second run
    if props.add_landing:
        
        top_landing_location = Vector((
            x_offset,
            (first_run_count - 1) * props.step_depth + props.step_depth / 2 - second_run_count * props.step_depth - (props.landing_depth/2 ),
            (first_run_count + second_run_count) * props.step_height +props.step_height
        ))
        create_landing(top_landing_location, (props.step_width, props.landing_depth, props.step_height), "Landing_Top")

# Draw Helix (Spiral) staircase with optional central landing
def create_helix_stairs(props):
    # Calculate angle increment per step
    total_rotation = props.helix_turns * 2 * math.pi  # Total rotation in radians
    angle_per_step = total_rotation / props.step_count
    
    # Create spiral steps
    for i in range(props.step_count):
        angle = i * angle_per_step
        
        # Calculate position on the spiral
        x = props.helix_radius * math.cos(angle)
        y = props.helix_radius * math.sin(angle)
        z = i * props.step_height
        
        location = Vector((x, y, z))
        
        # Calculate step rotation to align with spiral direction
        step_angle = angle + math.pi / 2  # Offset by 90 degrees for proper orientation
        
        # Create the step
        create_step(location, (props.helix_step_width, props.step_depth, props.step_height), f"Step_Helix_{i}")
        
        # Rotate the step to align with the spiral
        step = bpy.context.active_object
        step.rotation_euler[2] = step_angle  # Rotate around Z-axis
    
    # Optional central column/landing
    if props.add_landing and props.helix_central_column:
        # Create central support column
        column_height = props.step_count * props.step_height
        column_location = Vector((0, 0, column_height / 2))
        create_landing(column_location, (props.helix_column_radius * 2, props.helix_column_radius * 2, column_height), "Central_Column")
    
    # Optional top landing platform
    if props.add_landing and props.helix_top_platform:
        top_z = props.step_count * props.step_height
        platform_location = Vector((0, 0, top_z))
        platform_radius = props.helix_radius + props.helix_step_width
        create_landing(platform_location, (platform_radius, platform_radius, props.step_height), "Top_Platform")

# Draw T-Shape staircase with landings - Fixed positioning
def create_t_shape_stairs(props):
    central_count = props.t_central_run_count
    left_count = props.t_left_run_count
    right_count = props.t_right_run_count
    
    # Central vertical stem (along +Y)
    for i in range(central_count):
        x = 0
        y = i * props.step_depth
        z = i * props.step_height + props.step_height / 2
        create_step((x, y, z),
                    (props.step_width, props.step_depth, props.step_height),
                    f"Step_T_Center_{i}")
    
    # Calculate the exact position where central stem ends
    central_end_y = (central_count - 1) * props.step_depth
    central_end_z = central_count * props.step_height
    
    # Central landing at the T-junction - positioned to connect seamlessly with last step
    if props.add_landing:
        central_landing_location = Vector((
            0,
            central_end_y + props.step_depth / 2 + props.landing_depth / 2,
            central_end_z + props.step_height / 2
        ))
        # Calculate landing width to accommodate both arms
        max_arm_extent = max(left_count, right_count) * props.step_depth
        landing_width = props.step_width 
        create_landing(central_landing_location, (landing_width, props.landing_depth, props.step_height), "Landing_Center")
        
        # Update positions based on landing presence
        arm_start_y = central_end_y + props.step_depth / 2 + props.landing_depth/2
        arm_start_z = central_end_z 
    else:
        # No landing - arms start directly from the last central step
        arm_start_y = central_end_y + props.step_depth / 2
        arm_start_z = central_end_z
    
    # Left arm (along -X direction) - properly connected to central section
    for j in range(left_count):
        x = -(j+2 ) * props.step_depth - props.step_depth/8  # Start at -step_depth, not -(j+2)
        y = arm_start_y
        z = arm_start_z + j * props.step_height + props.step_height / 2 + props.step_height
        create_step((x, y, z),
                    (props.step_depth, props.step_width, props.step_height),
                    f"Step_T_Left_{j}")
    
    # Right arm (along +X direction) - properly connected to central section
    for k in range(right_count):
        x = (k+2 ) * props.step_depth + props.step_depth/8 # Start at +step_depth, not (k+2)
        y = arm_start_y
        z = arm_start_z + k * props.step_height + props.step_height / 2 + props.step_height
        create_step((x, y, z),
                    (props.step_depth, props.step_width, props.step_height),
                    f"Step_T_Right_{k}")
    
    # Left and right end landings - positioned at the end of each arm
    if props.add_landing:
        if left_count > 0:
            left_end_x = -left_count * props.step_depth -(props.step_depth*1.6)
            left_end_z = arm_start_z + (left_count +1)* props.step_height
            left_landing_location = Vector((
                left_end_x - props.landing_depth / 2,
                arm_start_y,
                left_end_z + props.step_height / 2
            ))
            create_landing(left_landing_location, (props.landing_depth, props.step_width, props.step_height), "Landing_Left")
        
        if right_count > 0:
            right_end_x = right_count * props.step_depth +(props.step_depth*1.6)
            right_end_z = arm_start_z + (right_count +1)* props.step_height
            right_landing_location = Vector((
                right_end_x + props.landing_depth / 2,
                arm_start_y,
                right_end_z + props.step_height / 2
            ))
            create_landing(right_landing_location, (props.landing_depth, props.step_width, props.step_height), "Landing_Right")
# Property group for UI
class StairProperties(bpy.types.PropertyGroup):
    # General properties (for Linear and Helix)
    step_count: bpy.props.IntProperty(name="Step Count", default=10, min=1, max=100, description="Number of steps for linear and helix staircases")
    step_width: bpy.props.FloatProperty(name="Step Width", default=1.0, min=0.1)
    step_height: bpy.props.FloatProperty(name="Step Height", default=0.2, min=0.05)
    step_depth: bpy.props.FloatProperty(name="Step Depth", default=0.3, min=0.1)
    add_landing: bpy.props.BoolProperty(name="Add Landings", default=True)
    landing_depth: bpy.props.FloatProperty(name="Landing Depth", default=1.0, min=0.5)
    
    # L-Shape staircase properties
    l_first_run_count: bpy.props.IntProperty(name="First Run Steps", default=6, min=1, max=50, description="Number of steps in the first run (along Y-axis)")
    l_second_run_count: bpy.props.IntProperty(name="Second Run Steps", default=4, min=1, max=50, description="Number of steps in the second run (along X-axis)")
    
    # U-Shape staircase properties
    u_first_run_count: bpy.props.IntProperty(name="First Run Steps", default=5, min=1, max=50, description="Number of steps in the first run (upward)")
    u_second_run_count: bpy.props.IntProperty(name="Second Run Steps", default=5, min=1, max=50, description="Number of steps in the second run (downward)")
    
    # T-Shape staircase properties
    t_central_run_count: bpy.props.IntProperty(name="Central Run Steps", default=5, min=1, max=50, description="Number of steps in the central stem")
    t_left_run_count: bpy.props.IntProperty(name="Left Arm Steps", default=3, min=0, max=50, description="Number of steps in the left arm (0 to disable)")
    t_right_run_count: bpy.props.IntProperty(name="Right Arm Steps", default=3, min=0, max=50, description="Number of steps in the right arm (0 to disable)")
    
    # Helix staircase properties
    helix_radius: bpy.props.FloatProperty(name="Helix Radius", default=2.0, min=0.5, description="Radius of the spiral staircase")
    helix_turns: bpy.props.FloatProperty(name="Number of Turns", default=2.0, min=0.5, max=10.0, description="How many full rotations the helix makes")
    helix_step_width: bpy.props.FloatProperty(name="Helix Step Width", default=0.8, min=0.2, description="Width of each step in the helix")
    helix_central_column: bpy.props.BoolProperty(name="Central Column", default=False, description="Add a central support column")
    helix_column_radius: bpy.props.FloatProperty(name="Column Radius", default=0.3, min=0.1, description="Radius of the central column")
    helix_top_platform: bpy.props.BoolProperty(name="Top Platform", default=True, description="Add a circular platform at the top")
    
    stair_type: bpy.props.EnumProperty(
        name="Stair Type",
        items=[
            ('LINEAR', "Linear", "Straight staircase with top landing"),
            ('L_SHAPE', "L-Shape", "Two runs with corner and top landings"),
            ('U_SHAPE', "U-Shape", "Two parallel runs with mid and top landings"),
            ('T_SHAPE', "T-Shape", "Central stem with two side branches and landings"),
            ('HELIX', "Helix", "Spiral staircase with optional central column and top platform")
        ],
        default='LINEAR'
    )

# Panel in UI
class VIEW3D_PT_StairGeneratorPanel(bpy.types.Panel):
    bl_label = "B_Stair Generator"
    bl_idname = "VIEW3D_PT_stair_generator"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Stair Generator"

    def draw(self, context):
        layout = self.layout
        props = context.scene.stair_props

        layout.prop(props, "stair_type")
        layout.separator()
        
        # Step count properties based on stair type
        count_box = layout.box()
        count_box.label(text="Step Counts:")
        
        if props.stair_type == 'LINEAR' or props.stair_type == 'HELIX':
            count_box.prop(props, "step_count")
        elif props.stair_type == 'L_SHAPE':
            count_box.prop(props, "l_first_run_count")
            count_box.prop(props, "l_second_run_count")
            # Display total count
            total_l = props.l_first_run_count + props.l_second_run_count
            count_box.label(text=f"Total Steps: {total_l}")
        elif props.stair_type == 'U_SHAPE':
            count_box.prop(props, "u_first_run_count")
            count_box.prop(props, "u_second_run_count")
            # Display total count
            total_u = props.u_first_run_count + props.u_second_run_count
            count_box.label(text=f"Total Steps: {total_u}")
        elif props.stair_type == 'T_SHAPE':
            count_box.prop(props, "t_central_run_count")
            count_box.prop(props, "t_left_run_count")
            count_box.prop(props, "t_right_run_count")
            # Display total count
            total_t = props.t_central_run_count + props.t_left_run_count + props.t_right_run_count
            count_box.label(text=f"Total Steps: {total_t}")
        
        # Step properties
        box = layout.box()
        box.label(text="Step Properties:")
        
        # Show different properties based on stair type
        if props.stair_type == 'HELIX':
            box.prop(props, "helix_step_width")
        else:
            box.prop(props, "step_width")
            
        box.prop(props, "step_height")
        
        if props.stair_type != 'HELIX':
            box.prop(props, "step_depth")
        
        # Helix-specific properties
        if props.stair_type == 'HELIX':
            helix_box = layout.box()
            helix_box.label(text="Helix Properties:")
            helix_box.prop(props, "helix_radius")
            helix_box.prop(props, "helix_turns")
            helix_box.prop(props, "step_depth", text="Step Depth (Radial)")
        
        # Landing properties
        box = layout.box()
        box.label(text="Landing Properties:")
        box.prop(props, "add_landing")
        
        if props.add_landing:
            if props.stair_type == 'HELIX':
                box.prop(props, "helix_central_column")
                if props.helix_central_column:
                    box.prop(props, "helix_column_radius")
                box.prop(props, "helix_top_platform")
            else:
                box.prop(props, "landing_depth")
        
        layout.separator()
        layout.operator("object.generate_stairs", icon="MESH_CUBE")

# Operator for generating stairs
class OBJECT_OT_GenerateStairs(bpy.types.Operator):
    bl_idname = "object.generate_stairs"
    bl_label = "Generate Stairs"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.stair_props
        delete_old_stairs()

        # Calculate total steps for reporting
        if props.stair_type == 'LINEAR' or props.stair_type == 'HELIX':
            total_steps = props.step_count
        elif props.stair_type == 'L_SHAPE':
            total_steps = props.l_first_run_count + props.l_second_run_count
        elif props.stair_type == 'U_SHAPE':
            total_steps = props.u_first_run_count + props.u_second_run_count
        elif props.stair_type == 'T_SHAPE':
            total_steps = props.t_central_run_count + props.t_left_run_count + props.t_right_run_count

        # Generate stairs based on type
        if props.stair_type == 'LINEAR':
            create_linear_stairs(props)
        elif props.stair_type == 'L_SHAPE':
            create_l_shape_stairs(props)
        elif props.stair_type == 'U_SHAPE':
            create_u_shape_stairs(props)
        elif props.stair_type == 'T_SHAPE':
            create_t_shape_stairs(props)
        elif props.stair_type == 'HELIX':
            create_helix_stairs(props)
        
        self.report({'INFO'}, f"Generated {props.stair_type} stairs with {total_steps} total steps")
        return {'FINISHED'}

# Register and unregister
classes = [
    StairProperties,
    VIEW3D_PT_StairGeneratorPanel,
    OBJECT_OT_GenerateStairs
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.stair_props = bpy.props.PointerProperty(type=StairProperties)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.stair_props

if __name__ == "__main__":
    register()