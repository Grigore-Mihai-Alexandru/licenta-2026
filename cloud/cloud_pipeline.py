import subprocess
import os
import re
import glob
import shutil
import argparse
from google.cloud import storage


def run_step(command, cwd=None):
    print(f"\n>>> {' '.join(command)}", flush=True)
    proc = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    for line in iter(proc.stdout.readline, ""):
        print(line, end="", flush=True)
    proc.stdout.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"Step failed (exit {proc.returncode}): {' '.join(command)}")


def parse_gcs_path(gcs_path: str) -> tuple[str, str]:
    path = gcs_path.replace("gs://", "")
    bucket, *parts = path.split("/")
    return bucket, "/".join(parts)


def download_from_gcs(gcs_path: str, local_dest: str) -> str:
    print(f"[GCS] Downloading {gcs_path} -> {local_dest}")
    bucket_name, blob_path = parse_gcs_path(gcs_path)
    client = storage.Client()
    client.bucket(bucket_name).blob(blob_path).download_to_filename(local_dest)
    return local_dest


def upload_folder_to_gcs(local_dir: str, gcs_output_path: str):
    print(f"[GCS] Uploading {local_dir} -> {gcs_output_path}")
    bucket_name, blob_prefix = parse_gcs_path(gcs_output_path)
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    for root, _, files in os.walk(local_dir):
        for file in files:
            local_path = os.path.join(root, file)
            relative   = os.path.relpath(local_path, local_dir)
            remote     = os.path.join(blob_prefix, relative).replace("\\", "/")
            bucket.blob(remote).upload_from_filename(local_path)
            print(f"  uploaded: {remote}")


def find_output_image(directory: str, name_no_ext: str) -> str | None:
    exact = os.path.join(directory, f"{name_no_ext}.png")
    if os.path.exists(exact):
        return exact
    candidates = glob.glob(os.path.join(directory, f"{name_no_ext}.*"))
    return candidates[0] if candidates else None


def find_output_obj(wonder3d_out_dir: str, name_no_ext: str) -> str | None:
    glb_candidates = glob.glob(
        os.path.join(wonder3d_out_dir, "**", "model.glb"), recursive=True
    )
    if glb_candidates:
        print(f"[MESH] Using GLB: {glb_candidates[0]}")
        return glb_candidates[0]

    expected = os.path.join(wonder3d_out_dir, name_no_ext, f"{name_no_ext}.obj")
    if os.path.exists(expected):
        return expected

    candidates = glob.glob(
        os.path.join(wonder3d_out_dir, "**", "*.obj"), recursive=True
    )
    # Skip the coarse intermediate mesh produced by Wonder3D
    candidates = [c for c in candidates if "init_3d_model" not in c]
    if candidates:
        print(f"[WARN] OBJ not at expected path, using: {candidates[0]}")
        return candidates[0]

    print(f"[WARN] No mesh found under {wonder3d_out_dir}")
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input_image",      type=str, required=True)
    parser.add_argument("--output_dir",       type=str, default="/app/outputs")
    parser.add_argument("--restormer_tasks",  type=str, default="Real_Denoising",
                        help="Comma-separated Restormer tasks: "
                             "Real_Denoising, Motion_Deblurring, "
                             "Single_Image_Defocus_Deblurring, Deraining, "
                             "Gaussian_Color_Denoising, Gaussian_Gray_Denoising")
    parser.add_argument("--crop",             type=int, default=160)
    parser.add_argument("--refine",           type=int, default=0)
    parser.add_argument("--wonder3d_mode",    type=str, default="official",
                        choices=["float16", "official"],
                        help="float16: low VRAM local GPU. official: full accuracy cloud L4.")
    parser.add_argument("--camera_type",      type=str, default="ortho",
                        choices=["ortho", "persp"])
    parser.add_argument("--mesh_faces",         type=int, default=8000)
    parser.add_argument("--mesh_stages",        type=int, default=1)
    parser.add_argument("--mesh_intermediate",  action="store_true")
    parser.add_argument("--mesh_print",         action="store_true",
                        help="Watertight repair and STL export on final mesh")
    parser.add_argument("--mesh_size",          type=float, default=50.0,
                        help="Scale mesh to this max dimension in mm (requires --mesh_print)")
    parser.add_argument("--mesh_infill",        type=float, default=0.20,
                        help="Infill ratio 0.0-1.0 for print cost estimate")
    parser.add_argument("--mesh_filament_cost",   type=float, default=65.0,
                        help="Filament cost in RON/kg for print cost estimate")
    parser.add_argument("--mesh_lod_watertight",  action="store_true",
                        help="Repair mesh holes before each LOD decimation stage")
    parser.add_argument("--skip_mesh", action="store_true",
                        help="Skip mesh optimization step entirely")
    parser.add_argument("--upscale", action="store_true",
                        help="Upscale input image with Real-ESRGAN x4 before Restormer")

    args = parser.parse_args()

    is_cloud_input  = args.input_image.startswith("gs://")
    is_cloud_output = args.output_dir.startswith("gs://")

    # GCS progress tracking: write a small JSON after each step so the UI
    # can poll it and update the step panel in real time.
    _prog_client = None
    _prog_bucket = None
    _prog_blob   = None

    if is_cloud_output:
        _pb, _pp   = parse_gcs_path(args.output_dir)
        _prog_client = storage.Client()
        _prog_bucket = _pb
        _prog_blob   = f"{_pp}/progress.json"
        try:
            import json as _j
            _prog_client.bucket(_prog_bucket).blob(_prog_blob).upload_from_string(
                _j.dumps({"step": -1}), content_type="application/json"
            )
        except Exception:
            pass

    def write_progress(step: int, name: str):
        if not _prog_client:
            return
        try:
            import json as _j
            _prog_client.bucket(_prog_bucket).blob(_prog_blob).upload_from_string(
                _j.dumps({"step": step, "name": name}),
                content_type="application/json",
            )
        except Exception:
            pass

    WONDER3D_SCRIPTS = {
        "float16":  "/app/Wonder3D/run_colab_float16.py",
        "official": "/app/Wonder3D/run_colab_official.py",
    }
    wonder3d_script = WONDER3D_SCRIPTS[args.wonder3d_mode]
    print(f"[CONFIG] Wonder3D mode: {args.wonder3d_mode} -> {wonder3d_script}")

    local_input_dir  = "/app/temp_input"
    local_output_dir = "/app/temp_output"
    os.makedirs(local_input_dir,  exist_ok=True)
    os.makedirs(local_output_dir, exist_ok=True)

    # -- 1. INPUT --------------------------------------------------------------

    if is_cloud_input:
        image_filename        = os.path.basename(args.input_image)
        current_working_image = download_from_gcs(
            args.input_image,
            os.path.join(local_input_dir, image_filename)
        )
    else:
        current_working_image = args.input_image

    name_no_ext = os.path.splitext(os.path.basename(current_working_image))[0]

    # -- 1. REAL-ESRGAN UPSCALING (optional) -----------------------------------

    if args.upscale:
        esrgan_out = os.path.join(local_input_dir, f"{name_no_ext}_esrgan.png")
        run_step([
            "/opt/venv_restormer/bin/python", "/app/upscale_esrgan.py",
            "--input",  current_working_image,
            "--output", esrgan_out,
            "--scale",  "4",
        ])
        current_working_image = esrgan_out
        name_no_ext = os.path.splitext(os.path.basename(esrgan_out))[0]
        print(f"[STEP 0] Real-ESRGAN done -> {current_working_image}")
        write_progress(0, "ESRGAN")

    # -- 2. RESTORMER ----------------------------------------------------------

    tasks = [t.strip() for t in args.restormer_tasks.split(",") if t.strip()]
    print(f"[CONFIG] Restormer tasks: {tasks}")

    for task in tasks:
        task_out_root = os.path.join(local_output_dir, "restoration_steps")
        run_step([
            "/opt/venv_restormer/bin/python", "/app/Restormer/demo.py",
            "--task",       task,
            "--input_dir",  current_working_image,
            "--result_dir", task_out_root,
        ], cwd="/app/Restormer")

        result_dir = os.path.join(task_out_root, task)
        found = find_output_image(result_dir, name_no_ext)
        if found:
            current_working_image = found
        else:
            raise RuntimeError(f"Restormer output not found in {result_dir}")

    print(f"[STEP 1] Restormer done -> {current_working_image}")
    write_progress(1, "Restormer")

    # -- 3. WONDER3D -----------------------------------------------------------

    wonder3d_out_dir = os.path.join(local_output_dir, "reconstruction")
    run_step([
        "/opt/venv_wonder3d/bin/python", wonder3d_script,
        "--input_path",  current_working_image,
        "--output_path", wonder3d_out_dir,
        "--crop_size",   str(args.crop),
        "--num_refine",  str(args.refine),
        "--camera_type", args.camera_type,
    ], cwd="/app/Wonder3D")

    print(f"[STEP 2] Wonder3D done -> {wonder3d_out_dir}")
    write_progress(2, "Wonder3D")

    # -- 4. MESH OPTIMIZATION --------------------------------------------------

    final_obj = find_output_obj(wonder3d_out_dir, name_no_ext)
    if args.skip_mesh:
        print("[STEP 3] Mesh optimization skipped.")
        write_progress(3, "Mesh")
    elif final_obj:
        base_name   = os.path.splitext(final_obj)[0]
        lowpoly_obj = base_name + "_lowpoly.obj"
        report_path = base_name + "_mesh_report.json"

        mesh_cmd = [
            "/opt/venv_wonder3d/bin/python", "/app/utils/optimize_mesh.py",
            "--input",         final_obj,
            "--output",        lowpoly_obj,
            "--faces",         str(args.mesh_faces),
            "--stages",        str(args.mesh_stages),
            "--report",        report_path,
            "--metrics",
            "--size",          str(args.mesh_size),
            "--infill",        str(args.mesh_infill),
            "--filament-cost", str(args.mesh_filament_cost),
        ]
        if args.mesh_intermediate:
            mesh_cmd.append("--intermediate")
        if args.mesh_lod_watertight:
            mesh_cmd.append("--lod-watertight")
        if args.mesh_print:
            mesh_cmd.append("--print")

        run_step(mesh_cmd, cwd="/app/utils")
        print(f"[STEP 3] Mesh optimization done -> {lowpoly_obj}")
        write_progress(3, "Mesh")
    else:
        print("[STEP 3] Skipped - no mesh found.")
        write_progress(3, "Mesh")

    # -- 5. OUTPUT -------------------------------------------------------------

    if is_cloud_output:
        upload_folder_to_gcs(local_output_dir, args.output_dir)
        print(f"[DONE] Results uploaded to {args.output_dir}")
    else:
        if local_output_dir != args.output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            shutil.copytree(local_output_dir, args.output_dir, dirs_exist_ok=True)
        print(f"[DONE] Results saved at {args.output_dir}")