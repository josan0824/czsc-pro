from dataclasses import dataclass, field
from typing import List

from Bi.BiList import CBiList
from Common.CEnum import BI_DIR, SEG_TYPE
from Common.func_util import revert_bi_dir

from .SegConfig import CSegConfig
from .SegListComm import CSegListComm


@dataclass
class _FeatureEle:
    stroke_idx: int
    high: float
    low: float
    all_sure: bool
    merged: bool = False
    merged_from: List[int] = field(default_factory=list)


@dataclass
class _Fractal:
    stroke_idx: int
    has_gap: bool
    all_sure: bool


@dataclass
class _PlanSeg:
    start_idx: int
    end_idx: int
    display_end_idx: int
    direction: BI_DIR
    is_sure: bool
    reason: str


class CSegListChanDoubao3(CSegListComm):
    """
    chan_doubao3 follows docs/新豆包规则 和代码.doc.

    The source document uses shared stroke endpoints between adjacent segments.
    This implementation maps a document endpoint stroke to the previous project
    segment's end at endpoint_idx - 1, so the next project segment starts from
    the document endpoint stroke and remains compatible with CSegListComm.
    """

    def __init__(self, seg_config=CSegConfig(seg_algo="chan_doubao3"), lv=SEG_TYPE.BI):
        super(CSegListChanDoubao3, self).__init__(seg_config=seg_config, lv=lv)
        self.display_segments = []

    def update(self, bi_lst: CBiList):
        self.do_init()
        plans = self._compute_plan(bi_lst)
        plans = self._merge_same_direction(plans)
        self.display_segments = self._build_display_segments(bi_lst, plans)
        self._apply_plan(bi_lst, plans)

    @staticmethod
    def _feature_from_bi(bi) -> _FeatureEle:
        return _FeatureEle(
            stroke_idx=bi.idx,
            high=bi._high(),
            low=bi._low(),
            all_sure=bi.is_used_to_be_sure,
        )

    @staticmethod
    def _build_feature_seq(bi_lst: CBiList, direction: BI_DIR, start_idx: int, end_idx: int) -> List[_FeatureEle]:
        target_dir = revert_bi_dir(direction)
        return [
            CSegListChanDoubao3._feature_from_bi(bi_lst[idx])
            for idx in range(start_idx, min(end_idx, len(bi_lst) - 1) + 1)
            if bi_lst[idx].dir == target_dir
        ]

    @staticmethod
    def _has_inclusion(left: _FeatureEle, right: _FeatureEle) -> bool:
        return (
            left.high >= right.high and left.low <= right.low
        ) or (
            right.high >= left.high and right.low <= left.low
        )

    @staticmethod
    def _left_contains_right(left: _FeatureEle, right: _FeatureEle) -> bool:
        return left.high >= right.high and left.low <= right.low

    @staticmethod
    def _process_inclusion(elements: List[_FeatureEle], seg_dir: BI_DIR) -> List[_FeatureEle]:
        if len(elements) < 2:
            return list(elements)

        take_low_low = seg_dir == BI_DIR.UP
        result = [_FeatureEle(**elements[0].__dict__)]
        for curr in elements[1:]:
            prev = result[-1]
            if not CSegListChanDoubao3._has_inclusion(prev, curr):
                result.append(_FeatureEle(**curr.__dict__))
                continue

            if len(result) == 1:
                if CSegListChanDoubao3._left_contains_right(prev, curr):
                    prev.merged = True
                    prev.merged_from.append(curr.stroke_idx)
                    prev.all_sure = prev.all_sure and curr.all_sure
                continue

            if take_low_low:
                prev.high = min(prev.high, curr.high)
                prev.low = min(prev.low, curr.low)
            else:
                prev.high = max(prev.high, curr.high)
                prev.low = max(prev.low, curr.low)
            prev.merged = True
            prev.merged_from.append(curr.stroke_idx)
            prev.all_sure = prev.all_sure and curr.all_sure
        return result

    @staticmethod
    def _find_fractals(elements: List[_FeatureEle], seg_dir: BI_DIR) -> List[_Fractal]:
        if len(elements) < 3:
            return []

        result: List[_Fractal] = []
        look_top = seg_dir == BI_DIR.DOWN
        for idx in range(1, len(elements) - 1):
            left, mid, right = elements[idx - 1], elements[idx], elements[idx + 1]
            if look_top and mid.high > left.high and mid.high > right.high:
                result.append(_Fractal(
                    stroke_idx=mid.stroke_idx,
                    has_gap=left.high < mid.low,
                    all_sure=left.all_sure and mid.all_sure and right.all_sure,
                ))
            elif not look_top and mid.low < left.low and mid.low < right.low:
                result.append(_Fractal(
                    stroke_idx=mid.stroke_idx,
                    has_gap=left.low > mid.high,
                    all_sure=left.all_sure and mid.all_sure and right.all_sure,
                ))
        return result

    @staticmethod
    def _confirm_reverse(bi_lst: CBiList, start_idx: int, direction: BI_DIR) -> bool:
        arr = []
        expected_dir = direction
        for idx in range(start_idx, len(bi_lst)):
            if bi_lst[idx].dir == expected_dir:
                arr.append(bi_lst[idx])
                expected_dir = revert_bi_dir(expected_dir)
            if len(arr) >= 3:
                break
        if len(arr) < 3:
            return False
        overlap_high = min(bi._high() for bi in arr[:3])
        overlap_low = max(bi._low() for bi in arr[:3])
        return overlap_high >= overlap_low

    @staticmethod
    def _is_valid_sure_range(bi_lst: CBiList, start_idx: int, end_idx: int, direction: BI_DIR) -> bool:
        if end_idx - start_idx < 2:
            return False
        if bi_lst[start_idx].dir != bi_lst[end_idx].dir:
            return False
        if direction == BI_DIR.UP:
            return bi_lst[start_idx].get_begin_val() < bi_lst[end_idx].get_end_val()
        return bi_lst[start_idx].get_begin_val() > bi_lst[end_idx].get_end_val()

    def _append_initial_tail(self, plans: List[_PlanSeg], bi_lst: CBiList, start_idx: int, direction: BI_DIR):
        if start_idx >= len(bi_lst):
            return
        plans.append(_PlanSeg(
            start_idx=start_idx,
            end_idx=len(bi_lst) - 1,
            display_end_idx=len(bi_lst) - 1,
            direction=direction,
            is_sure=False,
            reason="doubao3_initial",
        ))

    def _compute_plan(self, bi_lst: CBiList) -> List[_PlanSeg]:
        plans: List[_PlanSeg] = []
        if len(bi_lst) < 3:
            return plans

        seg_start = 0
        search_start = 0
        curr_dir = bi_lst[0].dir
        while search_start < len(bi_lst):
            raw_features = self._build_feature_seq(bi_lst, curr_dir, search_start, len(bi_lst) - 1)
            if len(raw_features) < 3:
                self._append_initial_tail(plans, bi_lst, seg_start, curr_dir)
                break

            processed_features = self._process_inclusion(raw_features, curr_dir)
            if len(processed_features) < 3:
                self._append_initial_tail(plans, bi_lst, seg_start, curr_dir)
                break

            fractals = self._find_fractals(processed_features, curr_dir)
            if not fractals:
                self._append_initial_tail(plans, bi_lst, seg_start, curr_dir)
                break

            first_fx = fractals[0]
            ended = False
            end_reason = "doubao3_no_gap"
            if not first_fx.has_gap:
                ended = True
            else:
                reverse_dir = revert_bi_dir(curr_dir)
                reverse_features = self._build_feature_seq(bi_lst, reverse_dir, first_fx.stroke_idx + 1, len(bi_lst) - 1)
                if len(reverse_features) >= 3:
                    reverse_processed = self._process_inclusion(reverse_features, reverse_dir)
                    reverse_fractals = self._find_fractals(reverse_processed, reverse_dir)
                    if reverse_fractals:
                        ended = True
                        end_reason = "doubao3_with_gap"

            if not ended:
                self._append_initial_tail(plans, bi_lst, seg_start, curr_dir)
                break

            project_end_idx = first_fx.stroke_idx - 1
            if project_end_idx < seg_start:
                self._append_initial_tail(plans, bi_lst, seg_start, curr_dir)
                break

            reverse_dir = revert_bi_dir(curr_dir)
            reverse_ok = self._confirm_reverse(bi_lst, first_fx.stroke_idx, reverse_dir)
            is_sure = first_fx.all_sure and self._is_valid_sure_range(bi_lst, seg_start, project_end_idx, curr_dir)
            plans.append(_PlanSeg(
                start_idx=seg_start,
                end_idx=project_end_idx,
                display_end_idx=first_fx.stroke_idx,
                direction=curr_dir,
                is_sure=is_sure,
                reason=end_reason,
            ))

            if not reverse_ok:
                self._append_initial_tail(plans, bi_lst, first_fx.stroke_idx, reverse_dir)
                break
            curr_dir = reverse_dir
            seg_start = first_fx.stroke_idx
            search_start = first_fx.stroke_idx

        return plans

    @staticmethod
    def _merge_same_direction(plans: List[_PlanSeg]) -> List[_PlanSeg]:
        merged: List[_PlanSeg] = []
        for plan in plans:
            if not merged:
                merged.append(plan)
                continue
            last = merged[-1]
            if last.direction == plan.direction:
                last.end_idx = plan.end_idx
                last.display_end_idx = plan.display_end_idx
                last.is_sure = last.is_sure and plan.is_sure
                if plan.reason != "doubao3_initial":
                    last.reason = plan.reason
            else:
                merged.append(plan)
        return merged

    @staticmethod
    def _build_display_segments(bi_lst: CBiList, plans: List[_PlanSeg]) -> List[dict]:
        display_segments = []
        for idx, plan in enumerate(plans):
            start_idx = max(0, min(plan.start_idx, len(bi_lst) - 1))
            end_idx = max(start_idx, min(plan.display_end_idx, len(bi_lst) - 1))
            bi_range = bi_lst[start_idx:end_idx + 1]
            if not bi_range:
                continue

            high = max(bi._high() for bi in bi_range)
            low = min(bi._low() for bi in bi_range)
            if plan.direction == BI_DIR.UP:
                begin_y, end_y = low, high
            else:
                begin_y, end_y = high, low

            display_segments.append({
                "idx": idx,
                "begin_bi_idx": start_idx,
                "end_bi_idx": end_idx,
                "begin_x": bi_lst[start_idx].get_begin_klu().idx,
                "end_x": bi_lst[end_idx].get_end_klu().idx,
                "begin_y": begin_y,
                "end_y": end_y,
                "dir": plan.direction,
                "is_sure": plan.is_sure,
                "reason": plan.reason,
            })
        return display_segments

    def _apply_plan(self, bi_lst: CBiList, plans: List[_PlanSeg]):
        for plan in plans:
            if plan.end_idx < plan.start_idx:
                continue
            expected_start = 0 if len(self.lst) == 0 else self.lst[-1].end_bi.idx + 1
            if plan.start_idx != expected_start:
                continue
            is_sure = plan.is_sure and self._is_valid_sure_range(bi_lst, plan.start_idx, plan.end_idx, plan.direction)
            self.add_new_seg(
                bi_lst,
                plan.end_idx,
                is_sure=is_sure,
                seg_dir=plan.direction,
                split_first_seg=False,
                reason=plan.reason,
            )
