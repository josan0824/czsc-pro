from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from Bi.Bi import CBi
from Common.CEnum import BI_DIR, KLINE_DIR, KL_TYPE, SEG_TYPE
from Common.func_util import revert_bi_dir

from .Eigen import CEigen
from .EigenFX import CEigenFX
from .SegConfig import CSegConfig
from .SegListChan import CSegListChan


@dataclass
class _V2FxEvent:
    seg_dir: BI_DIR
    peak_bi_idx: int
    evidence_bi_idx: int
    price: float
    all_sure: bool


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
            "desc": "线段v2.0形态分类：标准情况二；特征序列第一元素和第二元素之间有缺口。当前版本仍会继续寻找相反特征分型，并在过程中检查同类更极端特征分型或同向更极端笔端点是否可替代候选端点。",
        }
    return {
        "mode": "标准情况一",
        "desc": "线段v2.0形态分类：标准情况一；特征序列第一元素和第二元素之间无缺口。当前版本不再立即确认线段结束，而是继续寻找相反特征分型，并在过程中检查同类更极端特征分型或同向更极端笔端点是否可替代候选端点。",
    }


class CEigenFXV2(CEigenFX):
    """
    线段 v2.0 特征序列处理。

    与默认 chan 的主要差异：第一、第二特征元素不做包含合并。线段 v2.0
    仍记录这两个元素之间的缺口/无缺口关系作为形态分类，但两种情况
    都会进入后续相反特征分型确认和同类更极端候选替代流程。
    """

    def __init__(self, _dir: BI_DIR, exclude_included=True, lv=SEG_TYPE.BI):
        super(CEigenFXV2, self).__init__(_dir, exclude_included=exclude_included, lv=lv)
        self.final_end_bi_idx: Optional[int] = None
        self.v2_notes: List[str] = []
        self.v2_final_all_sure: Optional[bool] = None

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

    @staticmethod
    def _dir_fx_label(seg_dir: BI_DIR) -> str:
        return "顶分型" if seg_dir == BI_DIR.UP else "底分型"

    @staticmethod
    def _opposite_fx_label(seg_dir: BI_DIR) -> str:
        return "底分型" if seg_dir == BI_DIR.UP else "顶分型"

    @staticmethod
    def _event_bi_span(left: _V2FxEvent, right: _V2FxEvent) -> int:
        return abs(right.peak_bi_idx - left.peak_bi_idx) + 1

    @staticmethod
    def _event_has_three_bi(left: _V2FxEvent, right: _V2FxEvent) -> bool:
        return abs(right.peak_bi_idx - left.peak_bi_idx) >= 2

    @staticmethod
    def _is_more_extreme_event(event: _V2FxEvent, base: _V2FxEvent) -> bool:
        if base.seg_dir == BI_DIR.UP:
            return event.price > base.price
        return event.price < base.price

    @staticmethod
    def _pick_opposite_extreme(events: List[_V2FxEvent], same_dir: BI_DIR) -> Optional[_V2FxEvent]:
        if not events:
            return None
        if same_dir == BI_DIR.UP:
            return min(events, key=lambda event: event.price)
        return max(events, key=lambda event: event.price)

    @staticmethod
    def _is_more_extreme_opposite(event: _V2FxEvent, base: _V2FxEvent, same_dir: BI_DIR) -> bool:
        if same_dir == BI_DIR.UP:
            return event.price < base.price
        return event.price > base.price

    @staticmethod
    def _eigen_peak_bi_idx(eigen: CEigen) -> int:
        bi_dir = eigen.lst[0].dir
        if bi_dir == BI_DIR.UP:
            return eigen.get_peak_klu(is_high=False).idx - 1
        return eigen.get_peak_klu(is_high=True).idx - 1

    def _make_fx_event(self, eigen_fx: "CEigenFXV2") -> _V2FxEvent:
        peak_bi_idx = eigen_fx.GetPeakBiIdx()
        assert eigen_fx.ele[2] is not None
        price = eigen_fx.ele[1].high if eigen_fx.dir == BI_DIR.UP else eigen_fx.ele[1].low  # type: ignore
        return _V2FxEvent(
            seg_dir=eigen_fx.dir,
            peak_bi_idx=peak_bi_idx,
            evidence_bi_idx=eigen_fx.ele[2].lst[-1].idx,
            price=price,
            all_sure=eigen_fx.all_bi_is_sure(),
        )

    def _collect_fx_events(self, bi_list, seg_dir: BI_DIR, begin_idx: int) -> List[_V2FxEvent]:
        events: List[_V2FxEvent] = []
        if begin_idx >= len(bi_list):
            return events
        eigen_fx = CEigenFXV2(seg_dir, lv=self.lv)
        for bi in bi_list[begin_idx:]:
            if bi.dir == seg_dir:
                continue
            if eigen_fx.add(bi):
                while True:
                    events.append(self._make_fx_event(eigen_fx))
                    if not eigen_fx.reset():
                        break
        return events

    def _collect_same_endpoint_events(self, bi_list, begin_idx: int) -> List[_V2FxEvent]:
        events: List[_V2FxEvent] = []
        if begin_idx >= len(bi_list):
            return events
        for bi in bi_list[begin_idx:]:
            if bi.dir != self.dir:
                continue
            events.append(_V2FxEvent(
                seg_dir=self.dir,
                peak_bi_idx=bi.idx,
                evidence_bi_idx=bi.idx,
                price=bi.get_end_val(),
                all_sure=bi.is_used_to_be_sure,
            ))
        return events

    def can_be_end(self, bi_lst):
        assert self.ele[0] is not None and self.ele[1] is not None
        self.final_end_bi_idx = self.GetPeakBiIdx()
        self.v2_notes = []
        self.v2_final_all_sure = None
        gap_text = "有缺口" if self.ele[1].gap else "无缺口"
        self.v2_notes.append(
            f"chan_v2统一确认：第一、第二特征元素{gap_text}，初始候选{self._dir_fx_label(self.dir)}"
            f"位于第{self.final_end_bi_idx + 1}笔；不直接结束，继续寻找相反特征分型并检查同类更极端替代。"
        )
        first_event = _V2FxEvent(
            seg_dir=self.dir,
            peak_bi_idx=self._eigen_peak_bi_idx(self.ele[0]),
            evidence_bi_idx=self.ele[0].lst[-1].idx,
            price=self.ele[0].high if self.dir == BI_DIR.UP else self.ele[0].low,
            all_sure=next((False for bi in self.ele[0].lst if not bi.is_used_to_be_sure), True),
        )
        initial_event = _V2FxEvent(
            seg_dir=self.dir,
            peak_bi_idx=self.final_end_bi_idx,
            evidence_bi_idx=self.ele[1].lst[-1].idx,
            price=self.ele[1].high if self.dir == BI_DIR.UP else self.ele[1].low,
            all_sure=next((False for bi in self.ele[1].lst if not bi.is_used_to_be_sure), True),
        )
        if (
            initial_event.peak_bi_idx > first_event.peak_bi_idx
            and self._is_more_extreme_event(initial_event, first_event)
        ):
            self.v2_notes.append(
                f"初始特征分型已包含同类更极端替代：第{first_event.peak_bi_idx + 1}笔"
                f"替换为第{initial_event.peak_bi_idx + 1}笔，线段候选端点取最新"
                f"{self._dir_fx_label(self.dir)}。"
            )
        return self.find_revert_fx(bi_lst, self.final_end_bi_idx + 2, 0, 0)

    def find_revert_fx(self, bi_list, begin_idx: int, thred_value: float, break_thred: float):
        """
        v2 统一确认：无论第一、第二特征元素是否有缺口，都继续寻找相反
        特征分型；寻找过程中若出现更极端同类特征分型，按中间反向极值
        与最新同类分型至少三笔的规则判断是否替代候选端点。
        """
        assert self.ele[1] is not None and self.ele[2] is not None
        assert self.final_end_bi_idx is not None
        initial_event = _V2FxEvent(
            seg_dir=self.dir,
            peak_bi_idx=self.final_end_bi_idx,
            evidence_bi_idx=self.ele[2].lst[-1].idx,
            price=self.ele[1].high if self.dir == BI_DIR.UP else self.ele[1].low,
            all_sure=super(CEigenFXV2, self).all_bi_is_sure(),
        )
        current_event = initial_event
        current_all_sure = initial_event.all_sure

        if begin_idx >= len(bi_list):
            self.v2_notes.append("后续笔数不足，未找到相反特征分型；当前线段按未确认候选处理。")
            return None

        reverse_dir = revert_bi_dir(self.dir)
        same_begin_idx = self.ele[2].lst[0].idx
        same_events = [
            event for event in self._collect_fx_events(bi_list, self.dir, same_begin_idx)
            if event.evidence_bi_idx > initial_event.evidence_bi_idx and event.peak_bi_idx > initial_event.peak_bi_idx
        ]
        same_endpoint_events = [
            event for event in self._collect_same_endpoint_events(bi_list, initial_event.peak_bi_idx + 1)
            if event.evidence_bi_idx > initial_event.evidence_bi_idx and self._is_more_extreme_event(event, initial_event)
        ]
        reverse_events = self._collect_fx_events(bi_list, reverse_dir, begin_idx)
        events = sorted(
            [(event.evidence_bi_idx, "same", event) for event in same_events] +
            [(event.evidence_bi_idx, "same_endpoint", event) for event in same_endpoint_events] +
            [(event.evidence_bi_idx, "reverse", event) for event in reverse_events],
            key=lambda item: (item[0], 0 if item[1] in ("same", "same_endpoint") else 1),
        )

        reverse_candidate: Optional[_V2FxEvent] = None
        for _, kind, event in events:
            if kind == "reverse":
                if event.peak_bi_idx <= current_event.peak_bi_idx:
                    continue
                span = self._event_bi_span(current_event, event)
                if not self._event_has_three_bi(current_event, event):
                    self.v2_notes.append(
                        f"找到相反{self._opposite_fx_label(self.dir)}：第{event.peak_bi_idx + 1}笔，"
                        f"价格{event.price:g}；与当前{self._dir_fx_label(self.dir)}"
                        f"第{current_event.peak_bi_idx + 1}笔跨度{span}笔，不满足至少3笔，暂不作为确认候选。"
                    )
                    continue
                self.last_evidence_bi = bi_list[event.evidence_bi_idx]
                self.last_evidence_bi_is_sure = event.all_sure
                self.v2_final_all_sure = current_all_sure and event.all_sure
                self.v2_notes.append(
                    f"找到相反{self._opposite_fx_label(self.dir)}：第{event.peak_bi_idx + 1}笔，"
                    f"价格{event.price:g}；与当前{self._dir_fx_label(self.dir)}"
                    f"第{current_event.peak_bi_idx + 1}笔跨度{span}笔，满足至少3笔，"
                    f"立即确认，并以前一个同类{self._dir_fx_label(self.dir)}"
                    f"第{current_event.peak_bi_idx + 1}笔作为线段端点。"
                )
                return True
            if not self._is_more_extreme_event(event, current_event):
                continue

            between_reverse_events = [
                reverse_event for reverse_event in reverse_events
                if current_event.peak_bi_idx < reverse_event.peak_bi_idx < event.peak_bi_idx
            ]
            opposite_extreme = self._pick_opposite_extreme(between_reverse_events, self.dir)
            old_event = current_event
            current_event = event
            current_all_sure = event.all_sure
            self.final_end_bi_idx = event.peak_bi_idx
            if kind == "same_endpoint":
                self.v2_notes.append(
                    f"发现同向更极端笔端点：第{old_event.peak_bi_idx + 1}笔"
                    f"替换为第{event.peak_bi_idx + 1}笔，线段候选端点更新。"
                )
            else:
                self.v2_notes.append(
                    f"发现更极端同类{self._dir_fx_label(self.dir)}：第{old_event.peak_bi_idx + 1}笔"
                    f"替换为第{event.peak_bi_idx + 1}笔，线段候选端点更新。"
                )
            if opposite_extreme is not None:
                span = self._event_bi_span(opposite_extreme, event)
                if not self._event_has_three_bi(opposite_extreme, event):
                    self.v2_notes.append(
                        f"中间最极端相反{self._opposite_fx_label(self.dir)}"
                        f"第{opposite_extreme.peak_bi_idx + 1}笔与最新同类分型跨度{span}笔，"
                        f"不满足至少3笔，不替代之前的相反{self._opposite_fx_label(self.dir)}候选。"
                    )
                    continue
                if reverse_candidate is None or self._is_more_extreme_opposite(opposite_extreme, reverse_candidate, self.dir):
                    old_reverse_text = (
                        f"第{reverse_candidate.peak_bi_idx + 1}笔"
                        if reverse_candidate is not None else "空候选"
                    )
                    reverse_candidate = opposite_extreme
                    self.v2_notes.append(
                        f"中间最极端相反{self._opposite_fx_label(self.dir)}位于第{opposite_extreme.peak_bi_idx + 1}笔，"
                        f"与最新同类分型跨度{span}笔，满足至少3笔；用它替代之前的相反"
                        f"{self._opposite_fx_label(self.dir)}候选（{old_reverse_text}）。"
                    )
                else:
                    self.v2_notes.append(
                        f"中间最极端相反{self._opposite_fx_label(self.dir)}位于第{opposite_extreme.peak_bi_idx + 1}笔，"
                        f"跨度{span}笔，满足至少3笔，但未比当前相反候选更极端，不替代。"
                    )
            else:
                self.v2_notes.append(
                    f"两个同类{self._dir_fx_label(self.dir)}之间未出现相反特征分型，"
                    "仅更新线段候选端点。"
                )

        self.v2_final_all_sure = current_all_sure
        self.v2_notes.append("扫描至笔列表尾部仍未找到相反特征分型；当前线段按未确认候选处理。")
        return None

    def all_bi_is_sure(self):
        if self.v2_final_all_sure is not None:
            return self.v2_final_all_sure
        return super(CEigenFXV2, self).all_bi_is_sure()


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
        end_bi_idx = fx_eigen.final_end_bi_idx if fx_eigen.final_end_bi_idx is not None else fx_eigen.GetPeakBiIdx()
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
            self.lst[-1].v2_notes = list(getattr(fx_eigen, "v2_notes", []))
            if is_true:
                self.cal_seg_sure(bi_lst, end_bi_idx + 1)
        else:
            self.cal_seg_sure(bi_lst, fx_eigen.lst[1].idx)
