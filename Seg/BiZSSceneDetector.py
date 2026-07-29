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
    bi_count: int       # last - first + 1（不含破坏笔/离开笔）


@dataclass
class ZSSceneResult:
    zs_list: List[BiZSInfo]
    endpoint_bi_idx: int
    is_valid: bool = True
    invalid_reason: str = ""


@dataclass
class ZSBreakoutResult:
    """规则四触发结果：反向笔突破上一中枢边界。"""
    breakout_bi_idx: int   # 触发笔（反向突破笔）idx
    zs: BiZSInfo            # 被突破的上一中枢（zs_list[-1]）


def _intersects(bi, low: float, high: float) -> bool:
    """笔的 [low, high] 是否与中枢重叠区间 [low, high] 相交。"""
    return bi._high() >= low and bi._low() <= high


def _make_zs_info(bi_list, first: int, last: int, low: float, high: float) -> BiZSInfo:
    involved = bi_list[first:last + 1]
    return BiZSInfo(
        first_bi_idx=first,
        last_bi_idx=last,
        low=low,
        high=high,
        peak_low=min(bi._low() for bi in involved),
        peak_high=max(bi._high() for bi in involved),
        bi_count=last - first + 1,
    )


def detect_zs_scene(bi_list, begin_idx: int, end_idx: int, seg_dir) -> Optional[ZSSceneResult]:
    """
    判断 [begin_idx, end_idx] 区间内是否命中"笔中枢场景"。

    向上段：中枢从第一根向下笔起算；候选终点取区间内 _high() 最高的向上笔。
    向下段：中枢从第一根向上笔起算；候选终点取区间内 _low() 最低的向下笔。

    命中条件：
      1. 至少 1 个笔中枢（连续 3 笔重叠区间存在）；
      2. 每个用于端点替代的笔中枢笔数 <= 8；
      3. 相邻两中枢单调不重叠：向上段 a.ZG < b.ZD，向下段 a.ZD > b.ZG。
    未发现笔中枢返回 None。发现了超过 8 笔的笔中枢时返回 is_valid=False，
    调用方应保留该中枢用于灰色绘制，但不能用它启用同向单笔端点替代。

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
        leave = None
        j = f + 3
        while j <= end_idx:
            if _intersects(bi_list[j], low, high):
                j += 1
            else:
                leave = j
                break
        # 破坏笔(leave)不计入本中枢(注A)：last 指向最后一根与中枢区间重叠的笔；
        # 如果末尾重叠笔与进中枢笔方向相反，说明它只是尚未被反向笔确认的半组延伸，
        # 不计入本中枢；下一轮从被剔除笔处继续尝试。
        last = (leave - 1) if leave is not None else end_idx
        if bi_list[last].dir != enter_dir:
            last -= 1
        zs_list.append(_make_zs_info(bi_list, f, last, low, high))
        if leave is None:
            break
        i = last + 1

    if not zs_list:
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

    if any(z.bi_count > 8 for z in zs_list):
        return ZSSceneResult(
            zs_list=zs_list,
            endpoint_bi_idx=endpoint,
            is_valid=False,
            invalid_reason="over8",
        )
    # 相邻中枢须单调不重叠：向上段前低后高(a.ZG < b.ZD)，向下段前高后低(a.ZD > b.ZG)
    for a, b in zip(zs_list, zs_list[1:]):
        if is_up:
            if not (a.high < b.low):
                return None
        else:
            if not (a.low > b.high):
                return None

    return ZSSceneResult(zs_list=zs_list, endpoint_bi_idx=endpoint)


def detect_zs_breakout(bi_list, zs_list, seg_dir) -> Optional[ZSBreakoutResult]:
    """
    规则四触发判定：取候选段中枢列表的最后一个中枢（"上一中枢"），
    从该中枢之后起找第一根反向笔突破其边界。

      向下候选（seg_dir == DOWN）：找向上笔 _high() > zs.high（突破 ZG）。
      向上候选（seg_dir == UP）  ：找向下笔 _low() < zs.low（突破 ZD）。

    命中返回 ZSBreakoutResult(触发笔 idx, 中枢)；否则 None。
    触发对象是单根反向笔（非特征分型），因此比 reverse-fractal 确认更早触发。
    破坏笔不计入中枢外围极值（与规则五注A一致），故从 zs.last_bi_idx+1 起扫。
    """
    if not zs_list:
        return None
    zs = zs_list[-1]
    is_down_seg = seg_dir == BI_DIR.DOWN
    for k in range(zs.last_bi_idx + 1, len(bi_list)):
        bi = bi_list[k]
        if is_down_seg:
            if bi.dir == BI_DIR.UP and bi._high() > zs.high:
                return ZSBreakoutResult(breakout_bi_idx=k, zs=zs)
        else:
            if bi.dir == BI_DIR.DOWN and bi._low() < zs.low:
                return ZSBreakoutResult(breakout_bi_idx=k, zs=zs)
    return None
