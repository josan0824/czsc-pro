from typing import Any, Dict, List

from Bi.Bi import CBi
from Common.CEnum import BI_DIR, KLINE_DIR, KL_TYPE, SEG_TYPE
from Common.func_util import revert_bi_dir

from .Eigen import CEigen
from .EigenFX import CEigenFX
from .SegConfig import CSegConfig
from .SegListChan import CSegListChan


def _lv_to_label(lv) -> str:
    mapping = {
        KL_TYPE.K_1M: "1分钟",
        KL_TYPE.K_5M: "5分钟",
        KL_TYPE.K_15M: "15分钟",
        KL_TYPE.K_30M: "30分钟",
        KL_TYPE.K_60M: "60分钟",
        KL_TYPE.K_DAY: "日线",
        KL_TYPE.K_WEEK: "周线",
        KL_TYPE.K_MON: "月线",
    }
    return mapping.get(lv, "")


def _bi_to_pen_row(bi: CBi) -> Dict[str, Any]:
    return {
        "idx": int(bi.idx) + 1,
        "source_idx": int(bi.idx),
        "direction": "up" if bi.dir == BI_DIR.UP else "down",
        "begin_price": float(bi.get_begin_val()),
        "end_price": float(bi.get_end_val()),
    }


def classify_segment_v2_mode(
    label: str,
    component_pens: List[Dict[str, Any]],
    all_pens: List[Dict[str, Any]],
    direction: str,
    has_gap: bool = False,
) -> Dict[str, str]:
    if has_gap:
        return {
            "mode": "标准情况二",
            "desc": "线段v2.0形态分类：标准情况二；特征序列第一元素和第二元素之间有缺口，需要后续反向特征序列出现分型后确认线段结束。",
        }
    return {
        "mode": "标准情况一",
        "desc": "线段v2.0形态分类：标准情况一；特征序列第一元素和第二元素之间无缺口，当前特征序列形成对应分型后确认线段结束。",
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

    def find_revert_fx(self, bi_list, begin_idx: int, thred_value: float, break_thred: float):
        """
        情况二：第一、第二特征元素有缺口时，后一特征序列只要求出现分型。

        线段 v2.0 文档明确说明：第二个特征序列不要求回补前一缺口，
        也不再区分自身属于有缺口还是无缺口；出现分型即可确认。
        """
        if begin_idx >= len(bi_list):
            return None
        first_bi_dir = bi_list[begin_idx].dir
        eigen_fx = CEigenFXV2(revert_bi_dir(first_bi_dir), lv=self.lv)
        for bi in bi_list[begin_idx::2]:
            if eigen_fx.add(bi):
                assert eigen_fx.ele[2]
                self.last_evidence_bi = eigen_fx.ele[2].lst[-1]
                self.last_evidence_bi_is_sure = eigen_fx.all_bi_is_sure()
                return True
        return None


class CSegListChanV2(CSegListChan):
    def __init__(self, seg_config=CSegConfig(seg_algo="chan_v2"), lv=SEG_TYPE.BI):
        super(CSegListChanV2, self).__init__(seg_config=seg_config, lv=lv)

    def _level_label(self) -> str:
        return _lv_to_label(getattr(self.config, "seg_lv", None))

    def _classify_candidate(self, bi_lst, end_bi_idx: int, direction: BI_DIR, has_gap: bool) -> Dict[str, str]:
        label = self._level_label()
        if not label:
            return {}
        start_idx = 0 if len(self) == 0 else self[-1].end_bi.idx + 1
        component_pens = [_bi_to_pen_row(bi) for bi in bi_lst[start_idx:end_bi_idx + 1]]
        all_pens = [_bi_to_pen_row(bi) for bi in bi_lst]
        direction_text = "up" if direction == BI_DIR.UP else "down"
        return classify_segment_v2_mode(label, component_pens, all_pens, direction_text, has_gap=has_gap)

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

    def treat_fx_eigen(self, fx_eigen, bi_lst):
        _test = fx_eigen.can_be_end(bi_lst)
        end_bi_idx = fx_eigen.GetPeakBiIdx()
        if _test in [True, None]:
            is_true = _test is not None
            assert fx_eigen.ele[1] is not None
            mode_info = self._classify_candidate(bi_lst, end_bi_idx, fx_eigen.dir, has_gap=fx_eigen.ele[1].gap)
            reason = mode_info.get("mode", "chan_v2")
            if not self.add_new_seg(
                bi_lst,
                end_bi_idx,
                is_sure=is_true and fx_eigen.all_bi_is_sure(),
                reason=f"chan_v2_{reason}",
            ):
                self.cal_seg_sure(bi_lst, end_bi_idx + 1)
                return
            self.lst[-1].eigen_fx = fx_eigen
            if is_true:
                self.cal_seg_sure(bi_lst, end_bi_idx + 1)
        else:
            self.cal_seg_sure(bi_lst, fx_eigen.lst[1].idx)
