import ezdxf
import geopandas as gpd
import pandas as pd
import matplotlib.pyplot as plt
from shapely.geometry import Polygon, LineString, MultiLineString, Point
from pathlib import Path
import os
from datetime import datetime

def load_dxf_files(raw_path, edited_path):
    """Load DXF files and convert to GeoDataFrames for polylines and polygons."""
    try:
        raw_doc = ezdxf.readfile(raw_path)
        edited_doc = ezdxf.readfile(edited_path)
    except Exception as e:
        raise ValueError(f"Error loading DXF files: {e}")

    raw_features = []
    edited_features = []

    def extract_features(doc, feature_list, file_name):
        msp = doc.modelspace()
        entity_count = 0
        valid_count = 0
        
        # Query for more entity types to catch all possible geometries
        for entity in msp.query('LWPOLYLINE POLYLINE INSERT LINE ARC CIRCLE ELLIPSE SPLINE'):
            entity_count += 1
            entity_id = getattr(entity.dxf, 'handle', f'unknown_{entity_count}')
            geometry = None
            feature_type = None

            try:
                # Handle LWPOLYLINE
                if entity.dxftype() == 'LWPOLYLINE':
                    try:
                        points = list(entity.get_points('xy'))
                        if not points or len(points) < 2:
                            print(f"Warning: Skipping LWPOLYLINE (ID: {entity_id}) in {file_name} with insufficient points ({len(points)})")
                            continue
                        
                        # Convert to list of tuples
                        points = [(float(p[0]), float(p[1])) for p in points]
                        
                        # Check if closed
                        is_closed = getattr(entity, 'closed', False) or (len(points) > 2 and points[0] == points[-1])
                        
                        if is_closed and len(points) >= 3:
                            # Remove duplicate last point if it equals first
                            if points[0] == points[-1]:
                                points = points[:-1]
                            if len(points) >= 3:
                                geometry = Polygon(points)
                                feature_type = 'Polygon'
                        else:
                            geometry = LineString(points)
                            feature_type = 'LineString'
                    except Exception as e:
                        print(f"Warning: Error processing LWPOLYLINE (ID: {entity_id}): {e}")
                        continue

                # Handle POLYLINE
                elif entity.dxftype() == 'POLYLINE':
                    try:
                        vertices = list(entity.vertices) if hasattr(entity, 'vertices') and entity.vertices else []
                        if not vertices:
                            print(f"Warning: Skipping POLYLINE (ID: {entity_id}) in {file_name} with no vertices")
                            continue
                        
                        points = []
                        for v in vertices:
                            if hasattr(v, 'dxf') and hasattr(v.dxf, 'location'):
                                loc = v.dxf.location
                                points.append((float(loc[0]), float(loc[1])))
                        
                        if not points or len(points) < 2:
                            print(f"Warning: Skipping POLYLINE (ID: {entity_id}) in {file_name} with insufficient points ({len(points)})")
                            continue
                        
                        # Check if closed
                        is_closed = getattr(entity, 'is_closed', False) or (len(points) > 2 and points[0] == points[-1])
                        
                        if is_closed and len(points) >= 3:
                            # Remove duplicate last point if it equals first
                            if points[0] == points[-1]:
                                points = points[:-1]
                            if len(points) >= 3:
                                geometry = Polygon(points)
                                feature_type = 'Polygon'
                        else:
                            geometry = LineString(points)
                            feature_type = 'LineString'
                    except Exception as e:
                        print(f"Warning: Error processing POLYLINE (ID: {entity_id}): {e}")
                        continue

                # Handle LINE
                elif entity.dxftype() == 'LINE':
                    try:
                        start = entity.dxf.start
                        end = entity.dxf.end
                        points = [(float(start[0]), float(start[1])), (float(end[0]), float(end[1]))]
                        geometry = LineString(points)
                        feature_type = 'LineString'
                    except Exception as e:
                        print(f"Warning: Error processing LINE (ID: {entity_id}): {e}")
                        continue

                # Handle ARC
                elif entity.dxftype() == 'ARC':
                    try:
                        # Convert arc to line segments
                        center = entity.dxf.center
                        radius = entity.dxf.radius
                        start_angle = entity.dxf.start_angle
                        end_angle = entity.dxf.end_angle
                        
                        import math
                        # Create points along the arc
                        num_points = 20
                        angle_step = (end_angle - start_angle) / num_points
                        points = []
                        for i in range(num_points + 1):
                            angle = start_angle + i * angle_step
                            x = center[0] + radius * math.cos(math.radians(angle))
                            y = center[1] + radius * math.sin(math.radians(angle))
                            points.append((float(x), float(y)))
                        
                        if len(points) >= 2:
                            geometry = LineString(points)
                            feature_type = 'LineString'
                    except Exception as e:
                        print(f"Warning: Error processing ARC (ID: {entity_id}): {e}")
                        continue

                # Handle CIRCLE
                elif entity.dxftype() == 'CIRCLE':
                    try:
                        center = entity.dxf.center
                        radius = entity.dxf.radius
                        
                        import math
                        # Create points around the circle
                        num_points = 36
                        points = []
                        for i in range(num_points):
                            angle = 2 * math.pi * i / num_points
                            x = center[0] + radius * math.cos(angle)
                            y = center[1] + radius * math.sin(angle)
                            points.append((float(x), float(y)))
                        
                        geometry = Polygon(points)
                        feature_type = 'Polygon'
                    except Exception as e:
                        print(f"Warning: Error processing CIRCLE (ID: {entity_id}): {e}")
                        continue

                # Handle INSERT (blocks)
                elif entity.dxftype() == 'INSERT':
                    try:
                        block_name = getattr(entity.dxf, 'name', None)
                        if not block_name:
                            print(f"Warning: Skipping INSERT (ID: {entity_id}) in {file_name} with no block name")
                            continue
                        
                        if block_name in doc.blocks:
                            block = doc.blocks.get(block_name)
                            block_geometries = []
                            
                            for block_entity in block:
                                if block_entity.dxftype() == 'LWPOLYLINE':
                                    try:
                                        b_points = list(block_entity.get_points('xy'))
                                        b_points = [(float(p[0]), float(p[1])) for p in b_points]
                                        if len(b_points) >= 3:
                                            is_closed = getattr(block_entity, 'closed', False) or b_points[0] == b_points[-1]
                                            if is_closed:
                                                if b_points[0] == b_points[-1]:
                                                    b_points = b_points[:-1]
                                                if len(b_points) >= 3:
                                                    block_geometries.append(Polygon(b_points))
                                            else:
                                                block_geometries.append(LineString(b_points))
                                    except Exception as e:
                                        continue
                                elif block_entity.dxftype() == 'POLYLINE':
                                    try:
                                        b_vertices = list(block_entity.vertices) if hasattr(block_entity, 'vertices') and block_entity.vertices else []
                                        b_points = []
                                        for v in b_vertices:
                                            if hasattr(v, 'dxf') and hasattr(v.dxf, 'location'):
                                                loc = v.dxf.location
                                                b_points.append((float(loc[0]), float(loc[1])))
                                        if len(b_points) >= 3:
                                            is_closed = getattr(block_entity, 'is_closed', False) or b_points[0] == b_points[-1]
                                            if is_closed:
                                                if b_points[0] == b_points[-1]:
                                                    b_points = b_points[:-1]
                                                if len(b_points) >= 3:
                                                    block_geometries.append(Polygon(b_points))
                                            else:
                                                block_geometries.append(LineString(b_points))
                                    except Exception as e:
                                        continue
                            
                            if block_geometries:
                                # Use the first valid geometry from the block
                                geometry = block_geometries[0]
                                feature_type = geometry.geom_type
                        else:
                            print(f"Warning: Skipping INSERT (ID: {entity_id}) in {file_name} with missing block reference")
                            continue
                    except Exception as e:
                        print(f"Warning: Error processing INSERT (ID: {entity_id}): {e}")
                        continue

                # Validate geometry
                if geometry and hasattr(geometry, 'is_valid') and geometry.is_valid:
                    attributes = {'ID': entity_id, 'feature_type': feature_type}
                    
                    # Try to extract XData safely
                    try:
                        if hasattr(entity, 'has_xdata') and entity.has_xdata:
                            for appid in entity.xdata:
                                try:
                                    xdata = entity.get_xdata(appid)
                                    attributes[appid] = str(xdata)  # Convert to string to avoid serialization issues
                                except Exception:
                                    pass  # Skip problematic XData
                    except Exception:
                        pass  # Skip XData processing if it fails
                    
                    feature_list.append({'geometry': geometry, **attributes})
                    valid_count += 1
                else:
                    if geometry:
                        print(f"Warning: Skipping entity (ID: {entity_id}) in {file_name} due to invalid geometry")
                    else:
                        print(f"Warning: Skipping entity (ID: {entity_id}) in {file_name} - no geometry created")

            except Exception as e:
                print(f"Warning: Skipping entity (ID: {entity_id}) in {file_name} due to error: {e}")

        print(f"Processed {entity_count} entities in {file_name}, {valid_count} valid features found")
        return valid_count

    print(f"Processing raw file: {raw_path}")
    raw_valid = extract_features(raw_doc, raw_features, raw_path)
    print(f"Processing edited file: {edited_path}")
    edited_valid = extract_features(edited_doc, edited_features, edited_path)

    if not raw_features and not edited_features:
        raise ValueError(f"No valid features found in both DXF files. Processed {raw_valid} valid features in raw, {edited_valid} in edited.")
    elif not raw_features:
        print(f"Warning: No valid features found in raw DXF file ({raw_path}). Creating empty GeoDataFrame.")
        raw_features = [{'geometry': Point(0, 0), 'ID': 'dummy', 'feature_type': 'Point'}]
    elif not edited_features:
        print(f"Warning: No valid features found in edited DXF file ({edited_path}). Creating empty GeoDataFrame.")
        edited_features = [{'geometry': Point(0, 0), 'ID': 'dummy', 'feature_type': 'Point'}]

    raw_gdf = gpd.GeoDataFrame(raw_features, crs="EPSG:32633")  # Example UTM CRS, adjust as needed
    edited_gdf = gpd.GeoDataFrame(edited_features, crs=raw_gdf.crs)

    # Filter out dummy entries
    raw_gdf = raw_gdf[raw_gdf['ID'] != 'dummy']
    edited_gdf = edited_gdf[edited_gdf['ID'] != 'dummy']

    return raw_gdf, edited_gdf

def calculate_length(geometry):
    """Calculate the length of a geometry (boundary for polygons, direct for linestrings)."""
    if geometry.is_empty:
        return 0.0
    if geometry.geom_type == 'Polygon':
        boundary = geometry.boundary
        if isinstance(boundary, MultiLineString):
            return sum(line.length for line in boundary.geoms)
        elif isinstance(boundary, LineString):
            return boundary.length
    elif geometry.geom_type == 'LineString':
        return geometry.length
    elif geometry.geom_type == 'Point':
        return 0.0
    return 0.0

def compare_attributes(raw_row, edited_row, common_columns):
    """Compare attributes between two rows, ignoring geometry."""
    differences = {}
    for col in common_columns:
        if col != 'geometry' and raw_row[col] != edited_row[col]:
            differences[col] = {'raw': raw_row[col], 'edited': edited_row[col]}
    return differences

def analyze_edits(raw_gdf, edited_gdf):
    """Analyze additions, deletions, and modifications."""
    if len(raw_gdf) == 0 and len(edited_gdf) == 0:
        return {
            'additions': {'count': 0, 'length': 0.0, 'details': gpd.GeoDataFrame()},
            'deletions': {'count': 0, 'length': 0.0, 'details': gpd.GeoDataFrame()},
            'modifications': {'count': 0, 'length_diff': 0.0, 'details': []},
            'raw_stats': {'count': 0, 'total_length': 0.0},
            'edited_stats': {'count': 0, 'total_length': 0.0}
        }
    
    common_columns = list(set(raw_gdf.columns) & set(edited_gdf.columns))
    
    raw_gdf['length'] = raw_gdf.geometry.apply(calculate_length)
    edited_gdf['length'] = edited_gdf.geometry.apply(calculate_length)
    
    additions = edited_gdf[~edited_gdf['ID'].isin(raw_gdf['ID'])]
    additions_count = len(additions)
    additions_length = additions['length'].sum() if len(additions) > 0 else 0.0
    
    deletions = raw_gdf[~raw_gdf['ID'].isin(edited_gdf['ID'])]
    deletions_count = len(deletions)
    deletions_length = deletions['length'].sum() if len(deletions) > 0 else 0.0
    
    common_ids = set(raw_gdf['ID']) & set(edited_gdf['ID'])
    modifications = []
    modified_length_diff = 0.0
    
    for id_ in common_ids:
        raw_row = raw_gdf[raw_gdf['ID'] == id_].iloc[0]
        edited_row = edited_gdf[edited_gdf['ID'] == id_].iloc[0]
        
        geom_changed = not raw_row.geometry.equals(edited_row.geometry)
        length_diff = edited_row['length'] - raw_row['length']
        
        attr_diff = compare_attributes(raw_row, edited_row, common_columns)
        
        if geom_changed or attr_diff:
            modifications.append({
                'ID': id_,
                'geometry_changed': geom_changed,
                'attribute_changes': attr_diff,
                'length_difference': length_diff
            })
            modified_length_diff += abs(length_diff)
    
    modifications_count = len(modifications)
    
    return {
        'additions': {'count': additions_count, 'length': additions_length, 'details': additions},
        'deletions': {'count': deletions_count, 'length': deletions_length, 'details': deletions},
        'modifications': {'count': modifications_count, 'length_diff': modified_length_diff, 'details': modifications},
        'raw_stats': {'count': len(raw_gdf), 'total_length': raw_gdf['length'].sum()},
        'edited_stats': {'count': len(edited_gdf), 'total_length': edited_gdf['length'].sum()}
    }

def generate_comparison_table(stats):
    """Create a comparison table as a DataFrame."""
    data = {
        'Dataset': ['Raw', 'Edited', 'Additions', 'Deletions', 'Modifications'],
        'Feature Count': [
            stats['raw_stats']['count'],
            stats['edited_stats']['count'],
            stats['additions']['count'],
            stats['deletions']['count'],
            stats['modifications']['count']
        ],
        'Total Length (m)': [
            stats['raw_stats']['total_length'],
            stats['edited_stats']['total_length'],
            stats['additions']['length'],
            stats['deletions']['length'],
            stats['modifications']['length_diff']
        ]
    }
    return pd.DataFrame(data)

def plot_comparison(stats, output_dir, filename_prefix="comparison"):
    """Generate a bar graph comparing counts and lengths."""
    labels = ['Raw', 'Edited', 'Additions', 'Deletions', 'Modifications']
    counts = [
        stats['raw_stats']['count'],
        stats['edited_stats']['count'],
        stats['additions']['count'],
        stats['deletions']['count'],
        stats['modifications']['count']
    ]
    lengths = [
        stats['raw_stats']['total_length'],
        stats['edited_stats']['total_length'],
        stats['additions']['length'],
        stats['deletions']['length'],
        stats['modifications']['length_diff']
    ]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    
    ax1.bar(labels, counts, color=['blue', 'green', 'orange', 'red', 'purple'])
    ax1.set_title('Feature Count Comparison')
    ax1.set_ylabel('Count')
    ax1.tick_params(axis='x', rotation=45)
    
    ax2.bar(labels, lengths, color=['blue', 'green', 'orange', 'red', 'purple'])
    ax2.set_title('Length Comparison (m)')
    ax2.set_ylabel('Length (m)')
    ax2.tick_params(axis='x', rotation=45)
    
    plt.tight_layout()
    graph_path = output_dir / f'{filename_prefix}_graph.png'
    plt.savefig(graph_path, dpi=300, bbox_inches='tight')
    plt.close()
    return graph_path

def write_individual_report(stats, comparison_table, output_dir, filename):
    """Write a detailed editing report for individual file."""
    report_path = output_dir / f'{filename}_report.txt'
    with open(report_path, 'w') as f:
        f.write(f"Editing Statistics Report for: {filename}\n")
        f.write("=" * 60 + "\n\n")
        
        f.write("Summary Statistics:\n")
        f.write(f"Raw Dataset: {stats['raw_stats']['count']} features, "
                f"{stats['raw_stats']['total_length']:.2f} m total length\n")
        f.write(f"Edited Dataset: {stats['edited_stats']['count']} features, "
                f"{stats['edited_stats']['total_length']:.2f} m total length\n\n")
        
        f.write("Additions:\n")
        f.write(f"- Count: {stats['additions']['count']}\n")
        f.write(f"- Total Length: {stats['additions']['length']:.2f} m\n")
        if stats['additions']['count'] > 0:
            f.write("- Details:\n")
            for _, row in stats['additions']['details'].iterrows():
                f.write(f"  ID: {row['ID']}, Type: {row['feature_type']}, Length: {row['length']:.2f} m\n")
        f.write("\n")
        
        f.write("Deletions:\n")
        f.write(f"- Count: {stats['deletions']['count']}\n")
        f.write(f"- Total Length: {stats['deletions']['length']:.2f} m\n")
        if stats['deletions']['count'] > 0:
            f.write("- Details:\n")
            for _, row in stats['deletions']['details'].iterrows():
                f.write(f"  ID: {row['ID']}, Type: {row['feature_type']}, Length: {row['length']:.2f} m\n")
        f.write("\n")
        
        f.write("Modifications:\n")
        f.write(f"- Count: {stats['modifications']['count']}\n")
        f.write(f"- Total Absolute Length Difference: {stats['modifications']['length_diff']:.2f} m\n")
        if stats['modifications']['count'] > 0:
            f.write("- Details:\n")
            for mod in stats['modifications']['details']:
                f.write(f"  ID: {mod['ID']}\n")
                if mod['geometry_changed']:
                    f.write(f"    Geometry Changed, Length Difference: {mod['length_difference']:.2f} m\n")
                if mod['attribute_changes']:
                    f.write("    Attribute Changes:\n")
                    for attr, values in mod['attribute_changes'].items():
                        f.write(f"      {attr}: Raw={values['raw']}, Edited={values['edited']}\n")
        f.write("\n")
        
        f.write("Comparison Table:\n")
        f.write(comparison_table.to_string(index=False))
    
    return report_path

def write_overall_report(all_stats, output_dir):
    """Write an overall summary report for all processed files."""
    report_path = output_dir / 'OVERALL_SUMMARY_REPORT.txt'
    
    # Calculate totals
    total_files = len(all_stats)
    total_raw_features = sum(stat['raw_stats']['count'] for stat in all_stats.values())
    total_edited_features = sum(stat['edited_stats']['count'] for stat in all_stats.values())
    total_additions = sum(stat['additions']['count'] for stat in all_stats.values())
    total_deletions = sum(stat['deletions']['count'] for stat in all_stats.values())
    total_modifications = sum(stat['modifications']['count'] for stat in all_stats.values())
    total_raw_length = sum(stat['raw_stats']['total_length'] for stat in all_stats.values())
    total_edited_length = sum(stat['edited_stats']['total_length'] for stat in all_stats.values())
    total_additions_length = sum(stat['additions']['length'] for stat in all_stats.values())
    total_deletions_length = sum(stat['deletions']['length'] for stat in all_stats.values())
    total_modifications_length = sum(stat['modifications']['length_diff'] for stat in all_stats.values())
    
    with open(report_path, 'w') as f:
        f.write("OVERALL BATCH PROCESSING SUMMARY REPORT\n")
        f.write("=" * 60 + "\n")
        f.write(f"Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Files Processed: {total_files}\n\n")
        
        f.write("AGGREGATE STATISTICS:\n")
        f.write("-" * 30 + "\n")
        f.write(f"Total Raw Features: {total_raw_features}\n")
        f.write(f"Total Edited Features: {total_edited_features}\n")
        f.write(f"Total Additions: {total_additions}\n")
        f.write(f"Total Deletions: {total_deletions}\n")
        f.write(f"Total Modifications: {total_modifications}\n\n")
        
        f.write(f"Total Raw Length: {total_raw_length:.2f} m\n")
        f.write(f"Total Edited Length: {total_edited_length:.2f} m\n")
        f.write(f"Total Additions Length: {total_additions_length:.2f} m\n")
        f.write(f"Total Deletions Length: {total_deletions_length:.2f} m\n")
        f.write(f"Total Modifications Length Diff: {total_modifications_length:.2f} m\n\n")
        
        f.write("FILE-BY-FILE BREAKDOWN:\n")
        f.write("-" * 30 + "\n")
        f.write(f"{'Filename':<30} {'Raw':<8} {'Edited':<8} {'Add':<6} {'Del':<6} {'Mod':<6}\n")
        f.write("-" * 70 + "\n")
        
        for filename, stats in all_stats.items():
            f.write(f"{filename:<30} {stats['raw_stats']['count']:<8} "
                   f"{stats['edited_stats']['count']:<8} {stats['additions']['count']:<6} "
                   f"{stats['deletions']['count']:<6} {stats['modifications']['count']:<6}\n")
        
        f.write("\n" + "=" * 60 + "\n")
        f.write("End of Report\n")
    
    return report_path

def create_overall_summary_table(all_stats):
    """Create a comprehensive summary table for all files."""
    data = []
    for filename, stats in all_stats.items():
        data.append({
            'Filename': filename,
            'Raw_Features': stats['raw_stats']['count'],
            'Edited_Features': stats['edited_stats']['count'],
            'Additions': stats['additions']['count'],
            'Deletions': stats['deletions']['count'],
            'Modifications': stats['modifications']['count'],
            'Raw_Length_m': round(stats['raw_stats']['total_length'], 2),
            'Edited_Length_m': round(stats['edited_stats']['total_length'], 2),
            'Additions_Length_m': round(stats['additions']['length'], 2),
            'Deletions_Length_m': round(stats['deletions']['length'], 2),
            'Modifications_Length_Diff_m': round(stats['modifications']['length_diff'], 2)
        })
    
    return pd.DataFrame(data)

def get_dxf_files_from_folder(folder_path):
    """Get all DXF files from a folder."""
    folder = Path(folder_path)
    if not folder.exists():
        raise ValueError(f"Folder does not exist: {folder_path}")
    
    dxf_files = list(folder.glob("*.dxf"))
    dxf_files.extend(folder.glob("*.DXF"))  # Include uppercase extensions
    
    if not dxf_files:
        raise ValueError(f"No DXF files found in folder: {folder_path}")
    
    return dxf_files

def match_files(raw_files, edited_files):
    """Match raw and edited files by filename (without extension)."""
    raw_dict = {f.stem.lower(): f for f in raw_files}
    edited_dict = {f.stem.lower(): f for f in edited_files}
    
    matched_pairs = []
    unmatched_raw = []
    unmatched_edited = []
    
    for name, raw_file in raw_dict.items():
        if name in edited_dict:
            matched_pairs.append((raw_file, edited_dict[name]))
        else:
            unmatched_raw.append(raw_file)
    
    for name, edited_file in edited_dict.items():
        if name not in raw_dict:
            unmatched_edited.append(edited_file)
    
    return matched_pairs, unmatched_raw, unmatched_edited

def get_user_inputs():
    """Get folder paths and output directory from user."""
    while True:
        raw_folder = input("Enter path to folder containing raw DXF files: ").strip().strip('"')
        if os.path.isdir(raw_folder):
            try:
                get_dxf_files_from_folder(raw_folder)
                break
            except ValueError as e:
                print(f"Error: {e}")
        else:
            print("Invalid folder path or folder does not exist. Please try again.")

    while True:
        edited_folder = input("Enter path to folder containing edited DXF files: ").strip().strip('"')
        if os.path.isdir(edited_folder):
            try:
                get_dxf_files_from_folder(edited_folder)
                break
            except ValueError as e:
                print(f"Error: {e}")
        else:
            print("Invalid folder path or folder does not exist. Please try again.")

    while True:
        output_dir = input("Enter output directory path: ").strip().strip('"')
        if output_dir:
            break
        print("Output directory cannot be empty. Please try again.")

    return raw_folder, edited_folder, output_dir

def main():
    """Main function to generate batch editing reports."""
    try:
        raw_folder, edited_folder, output_dir = get_user_inputs()
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        print("Scanning for DXF files...")
        raw_files = get_dxf_files_from_folder(raw_folder)
        edited_files = get_dxf_files_from_folder(edited_folder)
        
        print(f"Found {len(raw_files)} raw DXF files and {len(edited_files)} edited DXF files")
        
        # Match files by name
        matched_pairs, unmatched_raw, unmatched_edited = match_files(raw_files, edited_files)
        
        if unmatched_raw:
            print(f"Warning: {len(unmatched_raw)} raw files have no matching edited files:")
            for f in unmatched_raw:
                print(f"  - {f.name}")
        
        if unmatched_edited:
            print(f"Warning: {len(unmatched_edited)} edited files have no matching raw files:")
            for f in unmatched_edited:
                print(f"  - {f.name}")
        
        if not matched_pairs:
            raise ValueError("No matching file pairs found. Please check that filenames match between folders.")
        
        print(f"Processing {len(matched_pairs)} matched file pairs...")
        
        all_stats = {}
        successful_processes = 0
        failed_processes = []
        
        # Process each matched pair
        for i, (raw_file, edited_file) in enumerate(matched_pairs, 1):
            filename = raw_file.stem
            print(f"\n[{i}/{len(matched_pairs)}] Processing: {filename}")
            
            try:
                # Load and analyze files
                raw_gdf, edited_gdf = load_dxf_files(str(raw_file), str(edited_file))
                stats = analyze_edits(raw_gdf, edited_gdf)
                
                # Generate individual reports
                comparison_table = generate_comparison_table(stats)
                
                # Save individual comparison table
                table_path = output_dir / f'{filename}_comparison_table.csv'
                comparison_table.to_csv(table_path, index=False)
                
                # Generate individual graph
                graph_path = plot_comparison(stats, output_dir, filename)
                
                # Write individual report
                report_path = write_individual_report(stats, comparison_table, output_dir, filename)
                
                # Store stats for overall report
                all_stats[filename] = stats
                successful_processes += 1
                
                print(f"  ✓ Individual report generated: {filename}_report.txt")
                print(f"  ✓ Comparison table saved: {filename}_comparison_table.csv")
                print(f"  ✓ Graph saved: {filename}_graph.png")
                
            except Exception as e:
                print(f"  ✗ Error processing {filename}: {e}")
                failed_processes.append((filename, str(e)))
        
        # Generate overall reports if any files were processed successfully
        if all_stats:
            print(f"\nGenerating overall summary reports...")
            
            # Write overall summary report
            overall_report_path = write_overall_report(all_stats, output_dir)
            
            # Create and save overall summary table
            overall_table = create_overall_summary_table(all_stats)
            overall_table_path = output_dir / 'OVERALL_SUMMARY_TABLE.csv'
            overall_table.to_csv(overall_table_path, index=False)
            
            # Generate overall statistics graph
            overall_stats = {
                'raw_stats': {
                    'count': sum(stat['raw_stats']['count'] for stat in all_stats.values()),
                    'total_length': sum(stat['raw_stats']['total_length'] for stat in all_stats.values())
                },
                'edited_stats': {
                    'count': sum(stat['edited_stats']['count'] for stat in all_stats.values()),
                    'total_length': sum(stat['edited_stats']['total_length'] for stat in all_stats.values())
                },
                'additions': {
                    'count': sum(stat['additions']['count'] for stat in all_stats.values()),
                    'length': sum(stat['additions']['length'] for stat in all_stats.values())
                },
                'deletions': {
                    'count': sum(stat['deletions']['count'] for stat in all_stats.values()),
                    'length': sum(stat['deletions']['length'] for stat in all_stats.values())
                },
                'modifications': {
                    'count': sum(stat['modifications']['count'] for stat in all_stats.values()),
                    'length_diff': sum(stat['modifications']['length_diff'] for stat in all_stats.values())
                }
            }
            
            overall_graph_path = plot_comparison(overall_stats, output_dir, "OVERALL_SUMMARY")
            
            print(f"  ✓ Overall summary report: {overall_report_path}")
            print(f"  ✓ Overall summary table: {overall_table_path}")
            print(f"  ✓ Overall summary graph: {overall_graph_path}")
        
        # Print final summary
        print("\n" + "="*70)
        print("BATCH PROCESSING COMPLETE!")
        print("="*70)
        print(f"Total file pairs found: {len(matched_pairs)}")
        print(f"Successfully processed: {successful_processes}")
        print(f"Failed to process: {len(failed_processes)}")
        
        if failed_processes:
            print("\nFailed files:")
            for filename, error in failed_processes:
                print(f"  - {filename}: {error}")
        
        if all_stats:
            print(f"\nOverall Statistics:")
            print(f"Total raw features: {sum(stat['raw_stats']['count'] for stat in all_stats.values())}")
            print(f"Total edited features: {sum(stat['edited_stats']['count'] for stat in all_stats.values())}")
            print(f"Total additions: {sum(stat['additions']['count'] for stat in all_stats.values())}")
            print(f"Total deletions: {sum(stat['deletions']['count'] for stat in all_stats.values())}")
            print(f"Total modifications: {sum(stat['modifications']['count'] for stat in all_stats.values())}")
            
            print(f"\nAll reports saved to: {output_dir}")
            print("Individual reports: [filename]_report.txt")
            print("Individual tables: [filename]_comparison_table.csv")
            print("Individual graphs: [filename]_graph.png")
            print("Overall summary: OVERALL_SUMMARY_REPORT.txt")
            print("Overall table: OVERALL_SUMMARY_TABLE.csv")
            print("Overall graph: OVERALL_SUMMARY_graph.png")
        
    except Exception as e:
        print(f"Critical Error: {e}")
        print("Please check your folder paths and try again.")

if __name__ == "__main__":
    main()