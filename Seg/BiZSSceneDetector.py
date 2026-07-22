from dataclasses import dataclass
from typing import List, Optional

from Common.CEnum import BI_DIR


@dataclass
class BiZSInfo:
    """笔中枢信息（笔维度，用于线段端点判定的场景检测）。"""
    first_bi_idx: int
    last_bi_idx: int
    low: float          # 中枢下限 = max(前3笔低点)，锁定
    high: float         # 中枢上限 = min(前3笔高点)，锁定
    peak_low: float     # 外围低点 = min(涉及笔低点)
    peak_high: float    # 外围高点 = max(涉及笔高点)
    bi_count: int       # last - first + 1（含离开笔）


@dataclass
class ZSSceneResult:
    zs_list: List[BiZSInfo]
    endpoint_bi_idx: int


def _intersects(bi, low: float, high: float) -> bool:
    """笔的 [low, high] 是否与中枢重叠区间 [low, high] 相交。"""
    return bi._high() >= low and bi._low() <= high


def detect_zs_scene(bi_list, begin_idx: int, end_idx: int, seg_dir) -> Optional[ZSSceneResult]:
    """
    判断 [begin_idx, end_idx] 区间内是否命中"笔中枢场景"。

    向上段：中枢从第一根向下笔起算；候选终点取区间内 _high() 最高的向上笔。
    向下段：中枢从第一根向上笔起算；候选终点取区间内 _low() 最低的向下笔。

    命中条件：
      1. 至少 1 个笔中枢（连续 3 笔重叠区间存在）；
      2. 每个笔中枢笔数 <= 8（含离开笔）；
      3. 相邻两中枢 [low, high] 不相交（相接即视为相交）。
    未命中返回 None。

    bi_list 元素只需提供 .dir(BI_DIR)、._high()、._low()。
    """
    if begin_idx < 0 or end_idx >= len(bi_list) or end_idx - begin_idx < 2:
        return None
    is_up = seg_dir == BI_DIR.UP
    enter_dir = BI_DIR.DOWN if is_up else BI_DIR.UP
    same_dir = seg_dir

    zs_list: List[BiZSInfo] = []
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
        zs_list.append(BiZSInfo(
            first_bi_idx=f,
            last_bi_idx=last,
            low=low,
            high=high,
            peak_low=peak_low,
            peak_high=peak_high,
            bi_count=last - f + 1,
        ))
        if leave is None:
            break
        i = last + 1

    if not zs_list:
        return None
    if any(z.bi_count > 8 for z in zs_list):
        return None
    for a, b in zip(zs_list, zs_list[1:]):
        if not (a.high < b.low or b.high < a.low):
            return None

    endpoint = begin_idx
    ext = None
    for k in range(begin_idx, end_idx + 1):
        bi = bi_list[k]
        if bi.dir != same_dir:
            continue
        v = bi._high() if is_up else bi._low()
        if ext is None or (is_up and v > ext) or (not is_up and v < ext):
            ext = v
            endpoint = k
    return ZSSceneResult(zs_list=zs_list, endpoint_bi_idx=endpoint)
