import pymeshlab as ml
import os
import sys
import argparse
import json
import time
import tempfile

try:
    import trimesh
    HAS_TRIMESH = True
except ImportError:
    HAS_TRIMESH = False
    print("[WARN] trimesh not installed. Run: pip install trimesh")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False


# Helpers

def get_stage_targets(initial_faces: int, target_faces: int, stages: int) -> list[int]:
    # Exponential decay: natural LOD progression (e.g. 500k → 250k → 125k → 60k)
    if stages <= 1:
        return [target_faces]
    ratio = (target_faces / initial_faces) ** (1.0 / stages)
    targets = []
    current = initial_faces
    for _ in range(stages - 1):
        current = int(current * ratio)
        targets.append(max(current, target_faces + 1))
    targets.append(target_faces)
    return targets


def decimate_to_target(ms: ml.MeshSet, target: int) -> bool:
    try:
        ms.apply_filter(
            "meshing_decimation_quadric_edge_collapse",
            targetfacenum=target,
            preservenormal=True,
            preservetopology=True,
            qualitythr=0.3,
            autoclean=True,
        )
        return True
    except Exception:
        pass
    try:
        ms.apply_filter(
            "simplification_quadric_edge_collapse_decimation",
            targetfacenum=target,
            preservenormal=True,
            preservetopology=True,
        )
        return True
    except Exception as e:
        print(f"  [ERROR] Both decimation filters failed: {e}")
        return False


def load_mesh(input_file: str) -> ml.MeshSet:
    # GLB/GLTF need trimesh to extract geometry first, pymeshlab can't load them directly
    if os.path.splitext(input_file)[1].lower() in (".glb", ".gltf") and HAS_TRIMESH:
        print("  [INFO] GLB detected — extracting geometry via trimesh...")
        mesh = trimesh.load(input_file, force="mesh")
        tmp = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
        tmp.close()
        mesh.export(tmp.name)
        ms = ml.MeshSet()
        ms.load_new_mesh(tmp.name)
        os.unlink(tmp.name)
        return ms
    ms = ml.MeshSet()
    ms.load_new_mesh(input_file)
    return ms


def save_mesh(ms: ml.MeshSet, path: str, export_stl: bool = False) -> tuple:
    base     = os.path.splitext(path)[0]
    obj_path = base + ".obj"
    glb_path = base + ".glb"
    stl_path = base + ".stl" if export_stl else None

    ms.save_current_mesh(obj_path, save_textures=False)

    # GLB via trimesh — pymeshlab GLB export is unreliable
    glb_path = None
    if HAS_TRIMESH:
        try:
            mesh = trimesh.load(obj_path, force="mesh")
            mesh.export(base + ".glb")
            glb_path = base + ".glb"
        except Exception as e:
            print(f"  [WARN] GLB export failed: {e}")

    if export_stl:
        try:
            ms.save_current_mesh(stl_path)
        except Exception as e:
            print(f"  [WARN] STL export failed: {e}")
            stl_path = None

    return obj_path, glb_path, stl_path


def collect_metrics(ms: ml.MeshSet, label: str, elapsed_s=None, file_path=None) -> dict:
    entry = {
        "label":    label,
        "faces":    ms.current_mesh().face_number(),
        "vertices": ms.current_mesh().vertex_number(),
    }
    if elapsed_s is not None:
        entry["elapsed_s"] = round(elapsed_s, 4)
    if file_path and os.path.exists(file_path):
        entry["file_size_kb"] = round(os.path.getsize(file_path) / 1024.0, 2)
    return entry


# Print pipeline helpers

def check_and_repair_watertight(ms: ml.MeshSet) -> dict:
    report = {"was_watertight": False, "repaired": False, "repair_steps": []}

    for filter_name, step_name in [
        ("meshing_repair_non_manifold_edges",    "non_manifold_edges"),
        ("meshing_close_holes",                  "close_holes"),
        ("meshing_repair_non_manifold_vertices", "non_manifold_vertices"),
    ]:
        try:
            kwargs = {"maxholesize": 30} if step_name == "close_holes" else {}
            ms.apply_filter(filter_name, **kwargs)
            report["repair_steps"].append(step_name)
        except Exception:
            pass

    try:
        ms.apply_filter(
            "meshing_remove_connected_component_by_face_number",
            mincomponentsize=25,
        )
        report["repair_steps"].append("remove_small_components")
    except Exception:
        pass

    if report["repair_steps"]:
        report["repaired"] = True

    if HAS_TRIMESH:
        try:
            tmp = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
            tmp.close()
            ms.save_current_mesh(tmp.name, save_textures=False)
            t = trimesh.load(tmp.name, force="mesh")
            os.unlink(tmp.name)
            report["was_watertight"]             = bool(t.is_watertight)
            report["is_watertight_after_repair"] = bool(t.is_watertight)
        except Exception:
            pass

    return report


def scale_to_size(ms: ml.MeshSet, target_mm: float) -> dict | None:
    bb     = ms.current_mesh().bounding_box()
    dims   = [bb.dim_x(), bb.dim_y(), bb.dim_z()]
    max_dim = max(dims)
    if max_dim <= 0:
        print("  [WARN] Invalid bounding box, skipping scale.")
        return None

    factor = target_mm / max_dim
    ms.apply_filter(
        "compute_matrix_from_scaling_or_normalization",
        axisx=factor, axisy=factor, axisz=factor,
    )
    return {
        "original_max_dim_mm": round(max_dim, 4),
        "target_mm":           target_mm,
        "scale_factor":        round(factor, 6),
        "scaled_dims_mm":      [round(d * factor, 3) for d in dims],
    }


def estimate_print_cost(
    ms: ml.MeshSet,
    infill: float = 0.20,
    filament_density: float = 1.24,
    filament_cost_per_kg: float = 25.0,
) -> dict | None:
    if not HAS_TRIMESH:
        print("  [WARN] trimesh required for cost estimation.")
        return None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
        tmp.close()
        ms.save_current_mesh(tmp.name, save_textures=False)
        t = trimesh.load(tmp.name, force="mesh")
        os.unlink(tmp.name)

        volume_mm3      = abs(float(t.volume))
        volume_cm3      = volume_mm3 / 1000.0
        surface_mm2     = float(t.area)
        shell_cm3       = (surface_mm2 * 1.2) / 1000.0          # 1.2mm shell
        infill_cm3      = max(0.0, volume_cm3 - shell_cm3) * infill
        material_cm3    = shell_cm3 + infill_cm3
        weight_g        = material_cm3 * filament_density
        cost_eur        = (weight_g / 1000.0) * filament_cost_per_kg

        return {
            "volume_cm3":           round(volume_cm3, 4),
            "estimated_material_cm3": round(material_cm3, 4),
            "estimated_weight_g":   round(weight_g, 2),
            "infill_pct":           int(infill * 100),
            "filament_cost_per_kg": filament_cost_per_kg,
            "estimated_cost_eur":   round(cost_eur, 3),
        }
    except Exception as e:
        print(f"  [WARN] Cost estimation failed: {e}")
        return None


# Main

def optimize_mesh(
    input_file: str,
    output_file: str,
    target_faces: int = 8000,
    stages: int = 1,
    save_intermediate: bool = False,
    report_path: str = None,
    print_mode: bool = False,
    target_size_mm: float = None,
    infill: float = 0.20,
    filament_cost: float = 25.0,
    log_metrics: bool = False,
) -> dict:
    if not os.path.exists(input_file):
        raise FileNotFoundError(f"Input mesh not found: {input_file}")

    stages  = max(1, min(5, stages))
    t_start = time.perf_counter()

    # Probe initial stats without keeping the MeshSet alive
    ms_probe         = load_mesh(input_file)
    initial_faces    = ms_probe.current_mesh().face_number()
    initial_vertices = ms_probe.current_mesh().vertex_number()
    del ms_probe

    print(f"\n[MESH] Input:    {os.path.basename(input_file)}")
    print(f"       Faces:    {initial_faces:,}")
    print(f"       Vertices: {initial_vertices:,}")
    print(f"       Target:   {target_faces:,} in {stages} stage(s)")
    print(f"       Mode:     Direct LOD (each level from original)\n")

    metrics_log      = []
    watertight_report = None

    if print_mode:
        print("[PRINT] Watertight repair...")
        ms_repair = load_mesh(input_file)
        watertight_report = check_and_repair_watertight(ms_repair)
        status = "OK" if watertight_report.get("is_watertight_after_repair") else "not fully watertight"
        print(f"  Steps: {watertight_report['repair_steps']}  →  {status}")
        # Save repaired mesh as the new source so LODs inherit repairs
        tmp_repaired = tempfile.NamedTemporaryFile(suffix=".obj", delete=False)
        tmp_repaired.close()
        ms_repair.save_current_mesh(tmp_repaired.name, save_textures=False)
        input_file = tmp_repaired.name
        del ms_repair

    if target_faces >= initial_faces:
        print("[WARN] Target >= input faces. No decimation needed.")
        ms = load_mesh(input_file)
        obj, glb, stl = save_mesh(ms, output_file, export_stl=print_mode)
        return {
            "input_faces": initial_faces, "output_faces": initial_faces,
            "reduction_pct": 0.0, "lod_mode": "none",
            "stages": [], "output_obj": obj, "output_glb": glb, "output_stl": stl,
        }

    stage_targets = get_stage_targets(initial_faces, target_faces, stages)
    print(f"[MESH] LOD targets: {' → '.join(f'{t:,}' for t in stage_targets)}\n")

    output_dir  = os.path.dirname(os.path.abspath(output_file))
    output_base = os.path.splitext(os.path.basename(output_file))[0]
    stage_results = []

    for i, target in enumerate(stage_targets):
        stage_num = i + 1
        is_last   = stage_num == len(stage_targets)

        # Direct LOD: reload original every time — preserves quadric error
        # matrices per level instead of accumulating degradation sequentially
        ms = load_mesh(input_file)

        print(f"[LOD {stage_num}/{stages}] {initial_faces:,} → {target:,}...")
        t0      = time.perf_counter()
        success = decimate_to_target(ms, target)
        elapsed = time.perf_counter() - t0

        if not success:
            print(f"  [ERROR] LOD {stage_num} failed. Stopping.")
            break

        faces_after    = ms.current_mesh().face_number()
        vertices_after = ms.current_mesh().vertex_number()
        reduction      = (1 - faces_after / initial_faces) * 100

        print(f"  ✓ {faces_after:,} faces, {vertices_after:,} verts  ({reduction:.1f}% from original)  {elapsed:.2f}s")

        stage_info = {
            "lod":            stage_num,
            "target":         target,
            "faces_after":    faces_after,
            "vertices_after": vertices_after,
            "reduction_pct":  round(reduction, 2),
            "elapsed_s":      round(elapsed, 4),
        }

        if log_metrics:
            metrics_log.append(collect_metrics(ms, f"lod_{stage_num}", elapsed_s=elapsed))

        if is_last:
            if print_mode and target_size_mm:
                print(f"\n[PRINT] Scaling to {target_size_mm}mm...")
                scale_info = scale_to_size(ms, target_size_mm)
                if scale_info:
                    print(f"  Factor: {scale_info['scale_factor']}  Dims: {scale_info['scaled_dims_mm']} mm")
                    stage_info["scale"] = scale_info

            obj, glb, stl = save_mesh(ms, output_file, export_stl=print_mode)
            stage_info["saved_obj"] = obj
            stage_info["saved_glb"] = glb
            stage_info["saved_stl"] = stl

        elif save_intermediate:
            lod_path = os.path.join(output_dir, f"{output_base}_lod{stage_num}.obj")
            obj, glb, stl = save_mesh(ms, lod_path)
            stage_info["saved_obj"] = obj
            stage_info["saved_glb"] = glb
            print(f"  Saved: {os.path.basename(obj)}")

        stage_results.append(stage_info)

    final_faces     = stage_results[-1]["faces_after"]
    final_vertices  = stage_results[-1]["vertices_after"]
    total_reduction = (1 - final_faces / initial_faces) * 100
    total_elapsed   = time.perf_counter() - t_start

    print_cost = None
    if print_mode:
        print("\n[PRINT] Estimating material cost...")
        ms_cost = load_mesh(stage_results[-1]["saved_obj"])
        print_cost = estimate_print_cost(ms_cost, infill=infill, filament_cost_per_kg=filament_cost)
        if print_cost:
            print(f"  Volume:   {print_cost['volume_cm3']} cm³")
            print(f"  Weight:   ~{print_cost['estimated_weight_g']}g  ({print_cost['infill_pct']}% infill)")
            print(f"  Est cost: ~{print_cost['estimated_cost_eur']} EUR")

    print(f"\n[MESH] Done in {total_elapsed:.2f}s")
    print(f"       {initial_faces:,} → {final_faces:,} faces  ({total_reduction:.1f}% reduction)")

    # Clean up temp repaired file if created
    if watertight_report and os.path.exists(input_file) and "tmp" in input_file:
        try:
            os.unlink(input_file)
        except Exception:
            pass

    report = {
        "input_file":      input_file,
        "input_faces":     initial_faces,
        "input_vertices":  initial_vertices,
        "output_faces":    final_faces,
        "output_vertices": final_vertices,
        "reduction_pct":   round(total_reduction, 2),
        "total_elapsed_s": round(total_elapsed, 4),
        "lod_mode":        "direct",
        "stages":          stage_results,
        "output_obj":      stage_results[-1].get("saved_obj"),
        "output_glb":      stage_results[-1].get("saved_glb"),
        "output_stl":      stage_results[-1].get("saved_stl"),
    }

    if watertight_report:
        report["watertight"] = watertight_report
    if print_cost:
        report["print_cost"] = print_cost
    if log_metrics:
        report["metrics_log"] = metrics_log

    if report_path:
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"       Report → {report_path}")

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Direct LOD mesh decimation")
    parser.add_argument("--input",         type=str,   required=True)
    parser.add_argument("--output",        type=str,   required=True)
    parser.add_argument("--faces",         type=int,   default=8000)
    parser.add_argument("--stages",        type=int,   default=1)
    parser.add_argument("--intermediate",  action="store_true",  help="Save each LOD as separate file")
    parser.add_argument("--report",        type=str,   default=None)
    parser.add_argument("--print",         dest="print_mode", action="store_true",
                        help="3D print pipeline: watertight repair + STL export + cost estimate")
    parser.add_argument("--size",          type=float, default=None,
                        help="Scale mesh to this max dimension in mm (requires --print)")
    parser.add_argument("--infill",        type=float, default=0.20,
                        help="Infill ratio 0.0–1.0 (default: 0.20)")
    parser.add_argument("--filament-cost", type=float, default=25.0,
                        help="Filament EUR/kg (default: 25.0)")
    parser.add_argument("--metrics",       action="store_true",
                        help="Log per-stage face count, file size, elapsed time in report")
    args = parser.parse_args()

    try:
        optimize_mesh(
            input_file=args.input,
            output_file=args.output,
            target_faces=args.faces,
            stages=args.stages,
            save_intermediate=args.intermediate,
            report_path=args.report,
            print_mode=args.print_mode,
            target_size_mm=args.size,
            infill=args.infill,
            filament_cost=args.filament_cost,
            log_metrics=args.metrics,
        )
        sys.exit(0)
    except Exception as e:
        print(f"\n[FATAL] {e}", file=sys.stderr)
        sys.exit(1)