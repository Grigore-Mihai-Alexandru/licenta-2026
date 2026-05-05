# run_wonder3d_official.py — Official Wonder3D_Plus runner (full precision, cloud L4)

import pyglet
pyglet.options['headless'] = True

import os
import sys
import gc

try:
    import transformers.utils.import_utils
    transformers.utils.import_utils.check_torch_load_is_safe = lambda: True
    os.environ["TRANSFORMERS_SKIP_CHECK_TORCH_LOAD"] = "1"
except Exception:
    pass

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(current_dir)
sys.path.append(os.path.join(current_dir, "MVMeshRecon"))

import torch
import argparse
from omegaconf import OmegaConf
from PIL import Image
import numpy as np

from run_mv_prediction import load_wonder3d_pipeline, pred_multiview_joint
from run_mv_enhancement import load_controlnet_pipeline, pred_enhancement_joint
from MVMeshRecon.Coarse_recon import coarse_recon
from MVMeshRecon.Iterative_refine import iterative_refine
from MVMeshRecon.utils.refine_lr_to_sr import sr_front
from rembg import remove


def clean_vram():
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()


def views_6to4(imgs):
    return [imgs[i] for i in range(6) if i not in (1, 5)]


def add_margin(pil_img, color=0, size=256):
    result = Image.new(pil_img.mode, (size, size), color)
    result.paste(pil_img, ((size - pil_img.width) // 2, (size - pil_img.height) // 2))
    return result


def process_image(image_input, image_size=2048, crop_size=1024 * 0.75):
    if np.asarray(image_input).shape[-1] == 3:
        image_input = remove(image_input)

    if crop_size != -1:
        alpha_np = np.asarray(image_input)[:, :, 3]
        coords   = np.stack(np.nonzero(alpha_np), 1)[:, (1, 0)]
        min_x, min_y = np.min(coords, 0)
        max_x, max_y = np.max(coords, 0)
        ref_img_ = image_input.crop((min_x, min_y, max_x, max_y))

        if ref_img_.width < 300 or ref_img_.height < 300:
            ref_img_ = sr_front(ref_img_)

        scale = crop_size / max(ref_img_.height, ref_img_.width)
        ref_img_ = ref_img_.resize((int(scale * ref_img_.width), int(scale * ref_img_.height)))
        image_input = add_margin(ref_img_, size=image_size)
    else:
        image_input = add_margin(image_input, size=max(image_input.height, image_input.width))
        image_input = image_input.resize((image_size, image_size))

    return image_input


if __name__ == "__main__":
    device = torch.device("cuda:0")

    parser = argparse.ArgumentParser()
    parser.add_argument("--config_mvdiffusion", type=str, default="configs/mvdiffusion-joint.yaml")
    parser.add_argument("--config_controlnet",  type=str, default="configs/controlnet.yaml")
    parser.add_argument("--input_path",  type=str, default="example_images/owl2.png")
    parser.add_argument("--output_path", type=str, default="outputs/")
    parser.add_argument("--seed",        type=int, default=42)
    parser.add_argument("--crop_size",   type=int, default=160)
    parser.add_argument("--camera_type", type=str, default="ortho")
    parser.add_argument("--num_refine",  type=int, default=1)
    args = parser.parse_args()

    config_mv          = OmegaConf.load(args.config_mvdiffusion)
    config_controlnet  = OmegaConf.load(args.config_controlnet)

    input_files = (
        [args.input_path] if not os.path.isdir(args.input_path)
        else [
            os.path.join(args.input_path, f)
            for f in os.listdir(args.input_path)
            if f.lower().endswith((".png", ".jpg"))
        ]
    )

    for image_file in input_files:
        try:
            print(f"\n[STEP 1] Generating multiviews for {image_file}...")

            mv_pipeline  = load_wonder3d_pipeline(config_mv).to(device)
            input_image  = process_image(Image.open(image_file),
                                         crop_size=args.crop_size * 8, image_size=2048)

            case_folder = os.path.join(args.output_path,
                                       os.path.basename(image_file).split(".")[0])
            os.makedirs(case_folder, exist_ok=True)
            input_image.save(os.path.join(case_folder, "front_img.png"))

            with torch.autocast(device_type="cuda"):
                normals_pred, images_pred = pred_multiview_joint(
                    input_image, mv_pipeline, seed=args.seed,
                    crop_size=args.crop_size, camera_type=args.camera_type,
                    cfg=config_mv, case_name=image_file,
                    output_path=args.output_path,
                )

            print("[STEP 1] Freeing diffusion model VRAM...")
            del mv_pipeline
            clean_vram()

            print("[STEP 2] Coarse mesh reconstruction...")
            rendered_rgbs, rendered_normal, vertices, faces = coarse_recon(
                front_image=input_image, rgbs=images_pred, normals=normals_pred,
                camera_type=args.camera_type,
                scence_name=os.path.basename(image_file).split(".")[0],
                crop_size=args.crop_size, output_path=args.output_path,
            )

            if args.num_refine > 0:
                print(f"[STEP 3] Iterative refinement (num_refine={args.num_refine})...")
                enhancement_pipeline = load_controlnet_pipeline(config_controlnet).to(device)

                mv_normals_4 = views_6to4(normals_pred)
                mv_imgs_4    = views_6to4(images_pred)

                for refine_idx in range(args.num_refine):
                    with torch.autocast(device_type="cuda"):
                        normals_enh, images_enh = pred_enhancement_joint(
                            mv_image=mv_imgs_4, mv_normlas=mv_normals_4,
                            renderd_mv_image=rendered_rgbs,
                            renderd_mv_normal=rendered_normal,
                            front_image=input_image,
                            pipeline=enhancement_pipeline,
                            seed=args.seed, crop_size=args.crop_size,
                            camera_type=args.camera_type,
                            cfg=config_controlnet, case_name=image_file,
                            refine_idx=refine_idx,
                            output_path=args.output_path,
                        )

                    _, _, vertices, faces = iterative_refine(
                        vertex_init=vertices, face_init=faces,
                        front_image=input_image,
                        rgbs=images_enh, normals=normals_enh,
                        camera_type=args.camera_type,
                        scence_name=os.path.basename(image_file).split(".")[0],
                        crop_size=args.crop_size, output_path=args.output_path,
                        refine_idx=refine_idx,
                        do_sr=(refine_idx == (args.num_refine - 1)),
                    )

                del enhancement_pipeline
                clean_vram()

            print(f"[DONE] Results in: {case_folder}")

        except Exception as e:
            print(f"[ERROR] {image_file}: {e}")
            clean_vram()
