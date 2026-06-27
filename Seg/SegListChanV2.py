from typing import Any, Dict, List, Optional

from Bi.Bi import CBi
from Common.CEnum import BI_DIR, KLINE_DIR, SEG_TYPE

from .Eigen import CEigen
from .EigenFX import CEigenFX
from .SegConfig import CSegConfig
from .SegListChan import CSegListChan


def _is_below_30m(label: str) -> bool:
    return label in ("1分钟", "5分钟", "15分钟")


def _pen_high(pen: Dict[str, Any]) -> float:
    return max(float(pen["begin_price"]), float(pen["end_price"]))


def _pen_low(pen: Dict[str, Any]) -> float:
    return min(float(pen["begin_price"]), float(pen["end_price"]))


def _range_contains(outer: Dict[str, Any], inner: Dict[str, Any]) -> bool:
    return _pen_high(outer) >= _pen_high(inner) and _pen_low(outer) <= _pen_low(inner)


def _has_range_overlap(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return max(_pen_low(a), _pen_low(b)) <= min(_pen_high(a), _pen_high(b))


def _feature_fx_kind(features: List[Dict[str, Any]]) -> Optional[str]:
    if len(features) < 3:
        return None
    a, b, c = features[0], features[1], features[2]
    if _pen_high(b) > _pen_high(a) and _pen_high(b) > _pen_high(c) and _pen_low(b) > _pen_low(a) and _pen_low(b) > _pen_low(c):
        return "top"
    if _pen_low(b) < _pen_low(a) and _pen_low(b) < _pen_low(c) and _pen_high(b) < _pen_high(a) and _pen_high(b) < _pen_high(c):
        return "bottom"
    return None


def _opposite_dir(direction: str) -> str:
    return "down" if direction == "up" else "up"


def classify_segment_v2_mode(
    label: str,
    component_pens: List[Dict[str, Any]],
    all_pens: List[Dict[str, Any]],
    direction: str,
) -> Dict[str, str]:
    if not _is_below_30m(label):
        return {
            "mode": "标准级别",
            "desc": "线段v2.0形态分类：当前级别不低于30分钟，优先按标准情况一/二处理，不启用复杂线段一到五预判。",
        }
    if len(component_pens) < 3:
        return {
            "mode": "普通模式",
            "desc": "线段v2.0形态分类：普通模式；当前段笔数不足以构成复杂线段一到五的完整结构。",
        }

    begin_idx = component_pens[0]["source_idx"]
    end_idx = component_pens[-1]["source_idx"]
    last_source_idx = all_pens[-1]["source_idx"] if all_pens else end_idx
    context = [pen for pen in all_pens if begin_idx <= pen["source_idx"] <= min(end_idx + 8, last_source_idx)]
    counter_dir = _opposite_dir(direction)
    counter_features = [pen for pen in context if pen["direction"] == counter_dir]

    for i, strong in enumerate(counter_features):
        later_same = counter_features[i + 1:i + 4]
        if len(later_same) >= 3 and all(_range_contains(strong, item) for item in later_same):
            later_context = [pen for pen in context if pen["source_idx"] > later_same[-1]["source_idx"]]
            breaks_original = any(
                (direction == "up" and pen["direction"] == "up" and _pen_high(pen) > _pen_high(strong))
                or (direction == "down" and pen["direction"] == "down" and _pen_low(pen) < _pen_low(strong))
                for pen in later_context
            )
            if breaks_original:
                return {
                    "mode": "复杂线段四",
                    "desc": (
                        f'线段v2.0形态分类：命中复杂线段四；第{strong["idx"]}笔之后至少三根同向反向特征元素'
                        "仍在该强反向笔范围内，属于中间状态，直到后续重新突破原方向关键极值才确认。"
                    ),
                }

    for i, strong in enumerate(context[:-3]):
        if strong["direction"] != counter_dir:
            continue
        next_two = context[i + 1:i + 3]
        if len(next_two) < 2 or not all(_range_contains(strong, item) for item in next_two):
            continue
        later = context[i + 3:]
        if direction == "up":
            break_counter = any(pen["direction"] == "down" and _pen_low(pen) < _pen_low(strong) for pen in later)
            break_origin = any(pen["direction"] == "up" and _pen_high(pen) > _pen_high(strong) for pen in later)
        else:
            break_counter = any(pen["direction"] == "up" and _pen_high(pen) > _pen_high(strong) for pen in later)
            break_origin = any(pen["direction"] == "down" and _pen_low(pen) < _pen_low(strong) for pen in later)
        if break_counter:
            return {
                "mode": "复杂线段二",
                "desc": (
                    f'线段v2.0形态分类：命中复杂线段二；第{strong["idx"]}笔为强反向笔，'
                    "后续两笔仍在其范围内，直到反向突破关键极值才确认原线段结束。"
                ),
            }
        if break_origin:
            return {
                "mode": "复杂线段三",
                "desc": (
                    f'线段v2.0形态分类：命中复杂线段三；第{strong["idx"]}笔为强反向笔，'
                    "后续两笔未形成有效反向线段，随后重新突破原方向极值，原线段延续。"
                ),
            }

    next_pens = [pen for pen in all_pens if end_idx < pen["source_idx"] <= end_idx + 8]
    if next_pens:
        first_break = next_pens[0]
        if first_break["direction"] == counter_dir:
            same_after_break = [pen for pen in next_pens[1:] if pen["direction"] == direction]
            opposite_after_break = [pen for pen in next_pens[1:] if pen["direction"] == first_break["direction"]]
            continuation = any(
                (direction == "down" and _pen_low(pen) < float(component_pens[-1]["end_price"]))
                or (direction == "up" and _pen_high(pen) > float(component_pens[-1]["end_price"]))
                for pen in same_after_break
            )
            reverse_line_break = len(opposite_after_break) >= 2 and any(
                not _has_range_overlap(first_break, pen) for pen in opposite_after_break
            )
            if reverse_line_break:
                return {
                    "mode": "复杂线段五-蓝色",
                    "desc": (
                        "线段v2.0形态分类：命中复杂线段五蓝色路径；一笔破坏后，后续反向走势已具备线段级别破坏特征，"
                        "可确认线段转换。"
                    ),
                }
            if continuation:
                return {
                    "mode": "复杂线段五-绿色/红色",
                    "desc": (
                        "线段v2.0形态分类：命中复杂线段五绿色/红色路径；一笔破坏后，同向走势继续突破原关键点，"
                        "按“线段必须被线段破坏”原则仍视为原线段延续。"
                    ),
                }

    if len(counter_features) >= 5:
        first_fx = _feature_fx_kind(counter_features[:3])
        has_later_inclusion = any(
            _range_contains(counter_features[i], counter_features[i + 1])
            or _range_contains(counter_features[i + 1], counter_features[i])
            for i in range(2, len(counter_features) - 1)
        )
        later_fx = _feature_fx_kind(counter_features[2:5])
        if first_fx and has_later_inclusion and later_fx is None:
            return {
                "mode": "复杂线段一",
                "desc": (
                    "线段v2.0形态分类：命中复杂线段一；前一特征序列已有分型，但后一组特征元素存在包含关系，"
                    "包含处理后反向分型不成立，因此不拆成多段。"
                ),
            }

    return {
        "mode": "普通模式",
        "desc": "线段v2.0形态分类：普通模式；当前低级别线段未命中复杂线段一到五，按标准情况一/二解释。",
    }


class CEigenFXV2(CEigenFX):
    """
    线段 v2.0 特征序列处理。

    与默认 chan 的主要差异：第一、第二特征元素不做包含合并。线段 v2.0
    依赖这两个元素之间的缺口/无缺口关系来决定是否需要后续反向确认，
    如果先按普通包含关系合并，可能会抹掉这个判定前提。
    """

    def treat_second_ele(self, bi: CBi) -> bool:
        assert self.ele[0] is not None
        self.ele[1] = CEigen(bi, self.kl_dir)
        if (self.is_up() and self.ele[1].high < self.ele[0].high) or \
           (self.is_down() and self.ele[1].low > self.ele[0].low):
            return self.reset()
        return False

    def reset(self):
        bi_tmp_list = list(self.lst[1:])
        self.clear()
        for bi in bi_tmp_list:
            if self.add(bi):
                return True
        return False


class CSegListChanV2(CSegListChan):
    def __init__(self, seg_config=CSegConfig(seg_algo="chan_v2"), lv=SEG_TYPE.BI):
        super(CSegListChanV2, self).__init__(seg_config=seg_config, lv=lv)

    def cal_seg_sure(self, bi_lst, begin_idx: int):
        up_eigen = CEigenFXV2(BI_DIR.UP, lv=self.lv)
        down_eigen = CEigenFXV2(BI_DIR.DOWN, lv=self.lv)
        last_seg_dir = None if len(self) == 0 else self[-1].dir
        for bi in bi_lst[begin_idx:]:
            fx_eigen = None
            if bi.is_down() and last_seg_dir != BI_DIR.UP:
                if up_eigen.add(bi):
                    fx_eigen = up_eigen
            elif bi.is_up() and last_seg_dir != BI_DIR.DOWN:
                if down_eigen.add(bi):
                    fx_eigen = down_eigen
            if len(self) == 0:
                if up_eigen.ele[1] is not None and bi.is_down():
                    last_seg_dir = BI_DIR.DOWN
                    down_eigen.clear()
                elif down_eigen.ele[1] is not None and bi.is_up():
                    up_eigen.clear()
                    last_seg_dir = BI_DIR.UP
                if up_eigen.ele[1] is None and last_seg_dir == BI_DIR.DOWN and bi.dir == BI_DIR.DOWN:
                    last_seg_dir = None
                elif down_eigen.ele[1] is None and last_seg_dir == BI_DIR.UP and bi.dir == BI_DIR.UP:
                    last_seg_dir = None

            if fx_eigen:
                self.treat_fx_eigen(fx_eigen, bi_lst)
                break
