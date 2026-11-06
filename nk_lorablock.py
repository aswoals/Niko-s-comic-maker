# -*- coding: utf-8 -*-
"""LoRA의 특정 층(블록)만 빼거나 약하게 한 복사본 만들기

    한 칸에 LoRA 캐릭터와 태그 캐릭터가 같이 있으면 그림체가 갈라지는 원인이기도 함.
근거: SDXL에서 그림체는 주로 output_blocks.1.1 (diffusers 이름 up_blocks.0.attentions.1, 흔히 OUT1)에, 캐릭터·내용은 OUT0 쪽에 있음
    (InstantStyle 논문 / Civitai 'Preventing style bleeding from character loras by selectively enabling blocks').
    그림체 층만 빼면 캐릭터는 남고 그림체는 작가 태그를 따를 것이라는 가설 (확인 전).
(같은 시드 비교)
원본 파일은 건드리지 않음. 새 파일은 ComfyUI loras 폴더에 씀 (ComfyUI는 목록을 새로 읽으므로 재시작 필요 없음)"""
import os
import sys

# kohya SDXL LoRA 키 이름 (lora_unet_ + 원래 층 이름의 '.'을 '_'로)
BLOCKS = {
    "out0": "lora_unet_output_blocks_0_1_",
    "out1": "lora_unet_output_blocks_1_1_",     # 그림체 (InstantStyle up_blocks.0.attentions.1)
    "out2": "lora_unet_output_blocks_2_1_",
    "in8": "lora_unet_input_blocks_8_1_",       # 배치·구도 쪽 그림체 (InstantStyle down_blocks.2.attentions.1)
    "mid": "lora_unet_middle_block_1_",
    "te": "lora_te",                             # 글 인코더 (트리거 단어)
}


def lora_dir():
    import nk
    return os.path.join(nk.COMFY_SHARED, "models", "loras")


def make(src_name, drops, scale=0.0, out_name=None):
    from safetensors.torch import load_file, save_file
    d = lora_dir()
    src = src_name if os.path.isabs(src_name) else os.path.join(d, src_name)
    if not os.path.exists(src):
        print("[ERROR] no LoRA file:", src); sys.exit(1)
    sd = load_file(src)
    pref = [BLOCKS[x] for x in drops]
    n_hit, out = 0, {}
    for k, v in sd.items():
        hit = any(k.startswith(p) for p in pref)
        # lora_up 만 곱하면 그 층 변화량이 scale 배 (down·alpha 는 그대로)
        if hit and (".lora_up." in k or k.endswith("lora_up.weight")):
            out[k] = (v * float(scale)).to(v.dtype); n_hit += 1
        else:
            out[k] = v
    if not n_hit:
        print("[ERROR] no key matched %s - key names look like: %s" % (drops, list(sd)[:3])); sys.exit(1)
    tag = "+".join(x.upper() for x in drops)
    name = out_name or "%s_%s.safetensors" % (os.path.splitext(os.path.basename(src))[0],
                                              ("no" + tag) if float(scale) == 0 else "%sx%g" % (tag, float(scale)))
    dst = os.path.join(d, name)
    save_file(out, dst, metadata={"nk_lorablock": "%s scale %g from %s" % (tag, float(scale), os.path.basename(src))})
    print("%d up-weights scaled x%g (%s) -> %s" % (n_hit, float(scale), tag, dst))
    return name


def run(nk, kit, args):
    drops = [x.strip().lower() for x in args.drop.split(",") if x.strip()]
    bad = [x for x in drops if x not in BLOCKS]
    if bad:
        print("[ERROR] unknown block %s (choose from %s)" % (bad, ", ".join(BLOCKS))); sys.exit(1)
    make(args.lora, drops, args.scale, args.out)


def add_parser(esub, nk, kit):
    a = esub.add_parser("lorablock", help="copy a LoRA with some blocks removed/scaled (e.g. out1 = style), for style tests")
    a.add_argument("lora", help="file name in ComfyUI models/loras, e.g. mychar_v1.safetensors")
    a.add_argument("--drop", default="out1", help="blocks: %s (comma list)" % ", ".join(BLOCKS))
    a.add_argument("--scale", type=float, default=0.0, help="0 = remove (default), 0.3 = keep 30%%")
    a.add_argument("--out", help="new file name (default <name>_noOUT1.safetensors)")
    a.set_defaults(func=lambda x: run(nk, kit, x))
