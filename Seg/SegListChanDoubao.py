from Bi.BiList import CBiList
from Common.CEnum import BI_DIR, SEG_TYPE

from .SegConfig import CSegConfig
from .SegListChan import CSegListChan


class CSegListChanDoubao(CSegListChan):
    """
    chan_doubao keeps chan's reverse eigen confirmation, but adds a conservative
    same-type endpoint replacement rule.

    A pending endpoint can be replaced by a more extreme same-direction bi only
    before an opposite-direction endpoint appears. Once an opposite endpoint is
    present between two same-type endpoints, the earlier endpoint is treated as
    locked and cannot be replaced by the later one.
    """

    def __init__(self, seg_config=CSegConfig(seg_algo="chan_doubao"), lv=SEG_TYPE.BI):
        super(CSegListChanDoubao, self).__init__(seg_config=seg_config, lv=lv)

    def update(self, bi_lst: CBiList):
        self.do_init()
        if len(self) == 0:
            self.cal_seg_sure(bi_lst, begin_idx=0)
        else:
            self.cal_seg_sure(bi_lst, begin_idx=self[-1].end_bi.idx + 1)
        self.extend_confirmed_seg_extremes(bi_lst)
        self.collect_left_seg(bi_lst)

    @staticmethod
    def _is_more_extreme(bi, candidate) -> bool:
        if candidate.dir == BI_DIR.DOWN:
            return bi._low() < candidate._low()
        return bi._high() > candidate._high()

    def _replace_until_opposite_fx(self, bi_lst: CBiList, begin_idx: int, end_idx: int, target_dir: BI_DIR):
        if bi_lst[begin_idx].dir != target_dir:
            return None
        candidate = bi_lst[begin_idx]
        for bi in bi_lst[begin_idx + 1:end_idx + 1]:
            if bi.dir != target_dir:
                break
            if self._is_more_extreme(bi, candidate):
                candidate = bi
        return candidate

    @staticmethod
    def _reset_seg_range(seg, bi_lst: CBiList, start_idx: int, end_idx: int):
        for bi in seg.bi_list:
            if bi.parent_seg is seg:
                bi.parent_seg = None
        seg.start_bi = bi_lst[start_idx]
        seg.end_bi = bi_lst[end_idx]
        seg.bi_list = []
        seg.support_trend_line = None
        seg.resistance_trend_line = None
        seg.clear_zs_lst()
        seg.update_bi_list(bi_lst, start_idx, end_idx)
        seg.check()

    def extend_confirmed_seg_extremes(self, bi_lst: CBiList):
        for seg_idx in range(len(self.lst) - 1):
            seg = self.lst[seg_idx]
            next_seg = self.lst[seg_idx + 1]
            if not seg.is_sure or seg.dir == next_seg.dir:
                continue

            end_bi = self._replace_until_opposite_fx(
                bi_lst,
                seg.end_bi.idx,
                next_seg.end_bi.idx,
                seg.end_bi.dir,
            )
            if end_bi is None or end_bi.idx <= seg.end_bi.idx:
                continue

            next_start_idx = end_bi.idx + 1
            if next_start_idx > next_seg.end_bi.idx:
                continue
            if next_seg.is_sure and next_seg.end_bi.idx - next_start_idx < 2:
                continue
            if bi_lst[next_start_idx].dir != next_seg.end_bi.dir:
                continue

            self._reset_seg_range(seg, bi_lst, seg.start_bi.idx, end_bi.idx)
            self._reset_seg_range(next_seg, bi_lst, next_start_idx, next_seg.end_bi.idx)
            seg.reason = "doubao_extend_until_next_confirm"

    def treat_fx_eigen(self, fx_eigen, bi_lst: CBiList):
        _test = fx_eigen.can_be_end(bi_lst)
        end_bi_idx = fx_eigen.GetPeakBiIdx()
        if _test in [True, None]:
            is_true = _test is not None
            evidence_bi = getattr(fx_eigen, "last_evidence_bi", None)
            search_end_idx = evidence_bi.idx if evidence_bi is not None else len(bi_lst) - 1
            if search_end_idx > end_bi_idx:
                end_bi = self._replace_until_opposite_fx(
                    bi_lst,
                    end_bi_idx,
                    search_end_idx,
                    bi_lst[end_bi_idx].dir,
                )
                if end_bi is not None:
                    end_bi_idx = end_bi.idx
            if not self.add_new_seg(bi_lst, end_bi_idx, is_sure=is_true and fx_eigen.all_bi_is_sure(), reason="doubao_extreme_end"):
                self.cal_seg_sure(bi_lst, end_bi_idx + 1)
                return
            self.lst[-1].eigen_fx = fx_eigen
            if is_true:
                self.cal_seg_sure(bi_lst, end_bi_idx + 1)
        else:
            self.cal_seg_sure(bi_lst, fx_eigen.lst[1].idx)

    def collect_left_as_seg(self, bi_lst: CBiList):
        last_seg_end_bi = self[-1].end_bi
        begin_idx = last_seg_end_bi.idx + 1
        if begin_idx >= len(bi_lst):
            return

        if last_seg_end_bi.is_up():
            target_dir = BI_DIR.DOWN
        else:
            target_dir = BI_DIR.UP

        end_bi = self._replace_until_opposite_fx(bi_lst, begin_idx, len(bi_lst) - 1, target_dir)
        if end_bi is None:
            return super().collect_left_as_seg(bi_lst)
        self.add_new_seg(bi_lst, end_bi.idx, is_sure=False, seg_dir=target_dir, reason="doubao_left_extreme")
