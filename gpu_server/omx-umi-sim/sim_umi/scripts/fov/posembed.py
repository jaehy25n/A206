"""The rectangular positional embedding for G2, and its unit tests.

    python sim_umi/scripts/fov/posembed.py          # runs the tests

pos_embed = [CLS | 14x14 patches]. The CLS row is copied unchanged; only the
patch rows are resampled:

    [196, D] -> [14, 14, D] -> [1, D, 14, 14] -> bicubic, align_corners=False,
    float32 -> [1, D, 11, 18] -> [198, D]

size is passed as (H, W) = (11, 18). timm lays patches out row-major, height
first (PatchEmbed flattens a [B, D, H, W] grid), which is the order used both
ways here.
"""
import sys

import torch
import torch.nn.functional as F


def rect_pos_embed(pe, src_hw=(14, 14), dst_hw=(11, 18), num_prefix=1):
    assert pe.dim() == 3 and pe.shape[0] == 1, pe.shape
    n_src = src_hw[0] * src_hw[1]
    if pe.shape[1] != num_prefix + n_src:
        raise ValueError(f"pos_embed has {pe.shape[1]} rows, expected {num_prefix} + {n_src}")
    D = pe.shape[2]
    prefix = pe[:, :num_prefix]
    grid = pe[:, num_prefix:].detach().to(torch.float32)
    grid = grid.reshape(1, src_hw[0], src_hw[1], D).permute(0, 3, 1, 2)         # [1, D, H, W]
    grid = F.interpolate(grid, size=tuple(dst_hw), mode="bicubic", align_corners=False)
    grid = grid.permute(0, 2, 3, 1).reshape(1, dst_hw[0] * dst_hw[1], D)         # row-major
    return torch.cat([prefix, grid.to(pe.dtype)], dim=1)


def _tests():
    torch.manual_seed(0)
    ok = True

    def check(name, cond, detail=""):
        nonlocal ok
        ok &= bool(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

    D = 768
    pe = torch.randn(1, 197, D)
    # 1. same size in, same values out
    same = rect_pos_embed(pe, dst_hw=(14, 14))
    check("identity at 14x14", torch.equal(same, pe), f"max |d| {float((same - pe).abs().max()):.2e}")
    # 2. shape, and the CLS row untouched
    out = rect_pos_embed(pe)
    check("shape [1, 199, 768]", tuple(out.shape) == (1, 199, D), str(tuple(out.shape)))
    check("CLS row copied bit for bit", torch.equal(out[:, 0], pe[:, 0]))
    # 3. orientation: channel 0 = row index, channel 1 = column index
    r, c = torch.meshgrid(torch.arange(14.), torch.arange(14.), indexing="ij")
    syn = torch.zeros(1, 197, D)
    syn[0, 1:, 0] = r.reshape(-1)
    syn[0, 1:, 1] = c.reshape(-1)
    o = rect_pos_embed(syn)[0, 1:].reshape(11, 18, D)
    rows_vary_down = bool((o[1:, :, 0] > o[:-1, :, 0]).all()) and float(o[:, :, 0].std(dim=1).max()) < 1e-5
    cols_vary_across = bool((o[:, 1:, 1] > o[:, :-1, 1]).all()) and float(o[:, :, 1].std(dim=0).max()) < 1e-5
    check("row index runs down 11 rows, constant across", rows_vary_down,
          f"first/last row {float(o[0, 0, 0]):.2f} / {float(o[-1, 0, 0]):.2f}")
    check("column index runs across 18 columns, constant down", cols_vary_across,
          f"first/last col {float(o[0, 0, 1]):.2f} / {float(o[0, -1, 1]):.2f}")
    # the swapped size would put 18 rows down: make sure that is not what we have
    wrong = rect_pos_embed(syn, dst_hw=(18, 11))[0, 1:].reshape(18, 11, D)
    check("(18, 11) is a different embedding (swap would be caught)", not torch.allclose(
        wrong.reshape(-1, D)[:198], o.reshape(-1, D)))
    # 4. agrees with timm's own resampler
    from timm.layers import resample_abs_pos_embed
    t = resample_abs_pos_embed(pe, new_size=(11, 18), num_prefix_tokens=1, interpolation="bicubic",
                               antialias=False, verbose=False)
    check("equals timm resample_abs_pos_embed (bicubic, no antialias)", torch.allclose(t, out, atol=1e-6),
          f"max |d| {float((t - out).abs().max()):.2e}")
    # 5. deterministic
    check("deterministic", torch.equal(rect_pos_embed(pe), rect_pos_embed(pe)))
    # 6. a ViT built for 176x288 takes it and yields 199 tokens and a 768 CLS
    import timm
    m = timm.create_model("vit_base_patch16_clip_224.openai", pretrained=False, global_pool="",
                          num_classes=0, img_size=(176, 288))
    check("timm ViT(176x288) grid", tuple(m.patch_embed.grid_size) == (11, 18) and tuple(m.pos_embed.shape) == (1, 199, D),
          f"grid {tuple(m.patch_embed.grid_size)} pos_embed {tuple(m.pos_embed.shape)}")
    m.pos_embed.data.copy_(out)
    m.eval()
    seen = {}
    h = m.blocks[0].register_forward_pre_hook(lambda mod, a: seen.__setitem__("t", tuple(a[0].shape)))
    with torch.no_grad():
        y = m(torch.rand(2, 3, 176, 288))
    h.remove()
    check("token sequence [2, 199, 768] and CLS [2, 768]", seen["t"] == (2, 199, D) and tuple(y[:, 0].shape) == (2, D),
          f"tokens {seen['t']} output {tuple(y.shape)}")
    # 7. and refuses the wrong input size instead of silently adapting
    try:
        with torch.no_grad():
            m(torch.rand(1, 3, 224, 224))
        check("224x224 into the 176x288 model is refused", False)
    except Exception as e:
        check("224x224 into the 176x288 model is refused", True, type(e).__name__)
    return ok


if __name__ == "__main__":
    sys.exit(0 if _tests() else 1)
