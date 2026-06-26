from dataclasses import dataclass
from typing import List, Optional, Tuple

from Bi.BiList import CBiList
from Common.CEnum import BI_DIR, SEG_TYPE
from Common.func_util import revert_bi_dir

from .SegConfig import CSegConfig
from .SegListComm import CSegListComm


@dataclass
class _FeatureEle:
    dir: BI_DIR
    low: float
    high: float
    idx: int
    all_sure: bool


class CSegListChanDoubao2(CSegListComm):
    """
    chan_doubao2 follows docs/豆包生成规则.doc:
    feature-sequence include handling, gap/non-gap confirmation, and reverse
    three-bi segment verification.
    """

    def __init__(self, seg_config=CSegConfig(seg_algo="chan_doubao2"), lv=SEG_TYPE.BI):
        super(CSegListChanDoubao2, self).__init__(seg_config=seg_config, lv=lv)

    def update(self, bi_lst: CBiList):
        self.do_init()
        self.cal_bi_sure(bi_lst)
        self.collect_left_seg(bi_lst)

    @staticmethod
    def _feature_from_bi(bi) -> _FeatureEle:
        return _FeatureEle(
            dir=bi.dir,
            low=bi._low(),
            high=bi._high(),
            idx=bi.idx,
            all_sure=bi.is_used_to_be_sure,
        )

    @staticmethod
    def _merge_feature_seq(feature_list: List[_FeatureEle], seg_dir: BI_DIR) -> List[_FeatureEle]:
        if len(feature_list) <= 1:
            return list(feature_list)

        merged = [feature_list[0]]
        for curr in feature_list[1:]:
            last = merged[-1]
            left_include_right = last.high >= curr.high and last.low <= curr.low
            right_include_left = curr.high >= last.high and curr.low <= last.low

            if len(merged) == 1:
                if left_include_right:
                    merged[-1] = CSegListChanDoubao2._merge_two_feature(last, curr, seg_dir)
                else:
                    merged.append(curr)
                continue

            if left_include_right or right_include_left:
                merged[-1] = CSegListChanDoubao2._merge_two_feature(last, curr, seg_dir)
            else:
                merged.append(curr)
        return merged

    @staticmethod
    def _merge_two_feature(left: _FeatureEle, right: _FeatureEle, seg_dir: BI_DIR) -> _FeatureEle:
        if seg_dir == BI_DIR.UP:
            low = min(left.low, right.low)
            high = min(left.high, right.high)
        else:
            low = max(left.low, right.low)
            high = max(left.high, right.high)
        return _FeatureEle(
            dir=left.dir,
            low=low,
            high=high,
            idx=left.idx,
            all_sure=left.all_sure and right.all_sure,
        )

    @staticmethod
    def _has_gap(f1: _FeatureEle, f2: _FeatureEle, seg_dir: BI_DIR) -> bool:
        if seg_dir == BI_DIR.UP:
            return f1.low > f2.high
        return f1.high < f2.low

    @staticmethod
    def _has_fx(seq: List[_FeatureEle], seg_dir: BI_DIR) -> bool:
        if len(seq) < 3:
            return False
        a, b, c = seq[-3], seq[-2], seq[-1]
        if seg_dir == BI_DIR.UP:
            return b.high > a.high and b.high > c.high
        return b.low < a.low and b.low < c.low

    @staticmethod
    def _check_reverse_segment(bi_lst: CBiList, start_idx: int, target_dir: BI_DIR) -> bool:
        if start_idx >= len(bi_lst) - 2:
            return False
        b0 = bi_lst[start_idx]
        b1 = bi_lst[start_idx + 1]
        b2 = bi_lst[start_idx + 2]
        if b0.dir != target_dir or b1.dir != revert_bi_dir(target_dir) or b2.dir != target_dir:
            return False
        overlap_low = max(b0._low(), b1._low(), b2._low())
        overlap_high = min(b0._high(), b1._high(), b2._high())
        return overlap_high > overlap_low

    @staticmethod
    def _feature_mid_to_seg_end_idx(feature_mid_idx: int, seg_start_idx: int, seg_dir: BI_DIR, bi_lst: CBiList) -> Optional[int]:
        end_idx = feature_mid_idx - 1
        if end_idx < seg_start_idx + 2:
            return None
        if end_idx >= len(bi_lst):
            return None
        if bi_lst[end_idx].dir != seg_dir:
            return None
        return end_idx

    @staticmethod
    def _is_valid_seg_range(bi_lst: CBiList, start_idx: int, end_idx: int, seg_dir: BI_DIR) -> bool:
        if end_idx - start_idx < 2:
            return False
        start_bi = bi_lst[start_idx]
        end_bi = bi_lst[end_idx]
        if start_bi.dir != end_bi.dir:
            return False
        if seg_dir == BI_DIR.UP:
            return start_bi.get_begin_val() < end_bi.get_end_val()
        return start_bi.get_begin_val() > end_bi.get_end_val()

    def _try_add_doc_seg(self, bi_lst: CBiList, end_idx: int, is_sure: bool, reason: str) -> bool:
        return self.add_new_seg(bi_lst, end_idx, is_sure=is_sure, reason=reason)

    def _scan_next_seg(self, bi_lst: CBiList, seg_start_idx: int) -> Tuple[Optional[int], bool]:
        curr_dir = bi_lst[seg_start_idx].dir
        feature_seq: List[_FeatureEle] = []
        warn_end_idx: Optional[int] = None
        warn_reverse_start_idx: Optional[int] = None
        warn_all_sure = False

        for bi in bi_lst[seg_start_idx:]:
            if bi.dir == revert_bi_dir(curr_dir):
                feature_seq.append(self._feature_from_bi(bi))

            merged_seq = self._merge_feature_seq(feature_seq, curr_dir)
            if len(merged_seq) < 3:
                continue
            if not self._has_fx(merged_seq, curr_dir):
                continue

            fx_mid = merged_seq[-2]
            end_idx = self._feature_mid_to_seg_end_idx(fx_mid.idx, seg_start_idx, curr_dir, bi_lst)
            if end_idx is None:
                continue
            if not self._is_valid_seg_range(bi_lst, seg_start_idx, end_idx, curr_dir):
                continue

            has_gap = self._has_gap(merged_seq[0], merged_seq[1], curr_dir)
            reverse_start_idx = end_idx + 1
            all_sure = all(ele.all_sure for ele in merged_seq[-3:])

            if not has_gap:
                if self._check_reverse_segment(bi_lst, reverse_start_idx, revert_bi_dir(curr_dir)):
                    return end_idx, all_sure
            elif warn_end_idx is None:
                warn_end_idx = end_idx
                warn_reverse_start_idx = reverse_start_idx
                warn_all_sure = all_sure
            elif warn_reverse_start_idx is not None and self._check_reverse_segment(
                bi_lst,
                warn_reverse_start_idx,
                revert_bi_dir(curr_dir),
            ):
                return warn_end_idx, warn_all_sure and all_sure

        return None, False

    def cal_bi_sure(self, bi_lst: CBiList):
        total = len(bi_lst)
        if total < 3:
            return

        seg_start_idx = 0
        while seg_start_idx <= total - 3:
            end_idx, all_sure = self._scan_next_seg(bi_lst, seg_start_idx)
            if end_idx is None:
                return
            if not self._try_add_doc_seg(
                bi_lst,
                end_idx,
                is_sure=all_sure,
                reason="doubao2_doc_rule",
            ):
                seg_start_idx += 1
                continue
            seg_start_idx = end_idx + 1
