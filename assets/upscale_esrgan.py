"""
Standalone Real-ESRGAN x4plus upscaler.
Called as a subprocess by cloud_pipeline.py using /opt/venv_restormer/bin/python,
which already has torch, cv2 and numpy installed.
"""
import argparse
import os

import cv2
import torch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",  required=True, help="Input image path")
    parser.add_argument("--output", required=True, help="Output image path")
    parser.add_argument("--scale",  type=int, default=4, choices=[2, 4],
                        help="Upscale factor (2 or 4, default 4)")
    args = parser.parse_args()

    from basicsr.archs.rrdbnet_arch import RRDBNet
    from realesrgan import RealESRGANer

    model = RRDBNet(
        num_in_ch=3, num_out_ch=3,
        num_feat=64, num_block=23, num_grow_ch=32, scale=4,
    )

    device = "cuda" if torch.cuda.is_available() else "cpu"
    upsampler = RealESRGANer(
        scale=4,
        model_path="/app/weights/RealESRGAN_x4plus.pth",
        model=model,
        tile=512,
        tile_pad=10,
        pre_pad=0,
        half=(device == "cuda"),
        device=device,
    )

    img = cv2.imread(args.input, cv2.IMREAD_UNCHANGED)
    if img is None:
        raise FileNotFoundError(f"Cannot read image: {args.input}")

    output, _ = upsampler.enhance(img, outscale=args.scale)

    # Cap the output to 1024 px on the longest side so the next Restormer step
    # does not OOM on local GPUs. ESRGAN already improved texture quality;
    # resizing back down preserves those gains at a manageable resolution.
    MAX_DIM = 1024
    h, w = output.shape[:2]
    if max(h, w) > MAX_DIM:
        ratio = MAX_DIM / max(h, w)
        new_w, new_h = int(w * ratio), int(h * ratio)
        output = cv2.resize(output, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        print(f"[ESRGAN] Capped output to {new_w}x{new_h} (max {MAX_DIM}px) to prevent VRAM overflow.")

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    cv2.imwrite(args.output, output)
    h_final, w_final = output.shape[:2]
    print(f"[ESRGAN] {os.path.basename(args.input)} -> {args.output}  ({w_final}x{h_final}, scale={args.scale}x, device={device})")


if __name__ == "__main__":
    main()
