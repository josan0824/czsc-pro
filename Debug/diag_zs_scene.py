"""诊断：为什么线段没命中笔中枢场景。

对每个线段，在 [start_bi.idx-1 .. end_bi.idx] 区间复跑 detect_zs_scene 的判定逻辑，
逐条报告命中/未命中及未命中原因。
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("TDX_HISTORY_DIR", str(_ROOT / "data" / "tdx"))

from datetime import datetime, timedelta
from Common.CEnum import AUTYPE, KL_TYPE, BI_DIR
from Chan import CChan
from ChanConfig import CChanConfig
from Seg.BiZSSceneDetector import _intersects


def diagnose_scene(bi_list, begin_idx, end_idx, seg_dir):
    """复跑 detect_zs_scene，返回 (hit, reason, zs_list)。"""
    if begin_idx < 0 or end_idx >= len(bi_list) or end_idx - begin_idx < 2:
        return False, f"区间笔数不足（需>=3，实际 {end_idx - begin_idx + 1} 笔）", []
    is_up = seg_dir == BI_DIR.UP
    enter_dir = BI_DIR.DOWN if is_up else BI_DIR.UP
    same_dir = seg_dir

    zs_list = []
    i = begin_idx
    while i <= end_idx:
        if bi_list[i].dir != enter_dir:
            i += 1
            continue
        f = i
        if f + 2 > end_idx:
            break
        b0, b1, b2 = bi_list[f], bi_list[f + 1], bi_list[f + 2]
        low = max(b0._low(), b1._low(), b2._low())
        high = min(b0._high(), b1._high(), b2._high())
        if not (high > low):
            i = f + 1
            continue
        peak_low = min(b0._low(), b1._low(), b2._low())
        peak_high = max(b0._high(), b1._high(), b2._high())
        leave = None
        j = f + 3
        while j <= end_idx:
            if _intersects(bi_list[j], low, high):
                peak_low = min(peak_low, bi_list[j]._low())
                peak_high = max(peak_high, bi_list[j]._high())
                j += 1
            else:
                leave = j
                break
        last = leave if leave is not None else end_idx
        zs_list.append((f, last, low, high, peak_low, peak_high, last - f + 1))
        if leave is None:
            break
        i = last + 1

    if not zs_list:
        return False, "区间内无笔中枢（找不到连续3笔重叠区间）", []
    over8 = [z for z in zs_list if z[6] > 8]
    if over8:
        return False, f"存在笔中枢笔数>8（含离开笔）：{[z[6] for z in over8]}", zs_list
    for a, b in zip(zs_list, zs_list[1:]):
        if not (a[3] < b[2] or b[3] < a[2]):  # a.high < b.low or b.high < a.low（相接即视为相交）
            return False, "相邻笔中枢 [low,high] 相交（中枢高低点未分离）", zs_list
    return True, f"命中：{len(zs_list)}个笔中枢", zs_list


def main():
    import sys
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    code = sys.argv[2] if len(sys.argv) > 2 else "SH000001"
    begin_time = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    config = CChanConfig({
        "bi_strict": True, "bi_fx_check": "totally", "bi_allow_sub_peak": True,
        "gap_as_kl": True, "seg_algo": "chan_v2", "seg_lv": KL_TYPE.K_1M,
        "trigger_step": False, "skip_step": 0, "divergence_rate": float("inf"),
        "bsp2_follow_1": False, "bsp3_follow_1": False, "min_zs_cnt": 0,
        "bs1_peak": False, "macd_algo": "peak",
        "bs_type": "1,2,3a,1p,2s,3b", "print_warning": False, "zs_algo": "normal",
    })
    chan = CChan(
        code=code, begin_time=begin_time, end_time=None,
        data_src="custom:TdxCacheAPI.CTdxCache", lv_list=[KL_TYPE.K_1M],
        config=config, autype=AUTYPE.NONE,
    )
    klc = chan[KL_TYPE.K_1M]
    bi_list = list(klc.bi_list)
    segs = klc.seg_list.lst

    print(f"bi 数: {len(bi_list)}  seg 数: {len(segs)}  区间: {begin_time} ~ now\n")
    for seg in segs:
        s, e = seg.start_bi.idx, seg.end_bi.idx
        hit, reason, zs = diagnose_scene(bi_list, max(0, s - 1), e, seg.dir)
        flag = "✓命中" if hit else "✗未命中"
        print(f"seg#{seg.idx} [{s}->{e}] {seg.dir.name:4} is_zs_scene={seg.is_zs_scene}  {flag}")
        print(f"        {reason}")
        if zs:
            for (f, last, low, high, pl, ph, cnt) in zs:
                print(f"        - 中枢 bi[{f}~{last}] 笔数={cnt} 区间[{low:.2f},{high:.2f}] 外围[{pl:.2f},{ph:.2f}]")
        print()


if __name__ == "__main__":
    main()
