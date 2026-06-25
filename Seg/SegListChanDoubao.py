from Bi.BiList import CBiList
from Common.CEnum import BI_DIR, SEG_TYPE

from .SegConfig import CSegConfig
from .SegListChan import CSegListChan


class CSegListChanDoubao(CSegListChan):
    """
    chan_doubao keeps chan's reverse eigen confirmation, but delays the segment
    endpoint choice until that confirmation window is known.

    Before a reverse segment confirms the pending segment, the pending endpoint
    is replaced by a more extreme same-type bi endpoint in the confirmation
    window. Already confirmed historical segments are not rewritten later.
    """

    def __init__(self, seg_config=CSegConfig(seg_algo="chan_doubao"), lv=SEG_TYPE.BI):
        super(CSegListChanDoubao, self).__init__(seg_config=seg_config, lv=lv)

    @staticmethod
    def _more_extreme_end_bi(bi_lst: CBiList, begin_idx: int, end_idx: int, target_dir: BI_DIR):
        candidates = [
            bi for bi in bi_lst[begin_idx:end_idx + 1]
            if bi.dir == target_dir
        ]
        if not candidates:
            return None
        if target_dir == BI_DIR.DOWN:
            return min(candidates, key=lambda bi: bi._low())
        return max(candidates, key=lambda bi: bi._high())

    def treat_fx_eigen(self, fx_eigen, bi_lst: CBiList):
        _test = fx_eigen.can_be_end(bi_lst)
        end_bi_idx = fx_eigen.GetPeakBiIdx()
        if _test in [True, None]:
            is_true = _test is not None
            evidence_bi = getattr(fx_eigen, "last_evidence_bi", None)
            search_end_idx = evidence_bi.idx if evidence_bi is not None else len(bi_lst) - 1
            if search_end_idx > end_bi_idx:
                end_bi = self._more_extreme_end_bi(
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
            end_bi = min(
                (bi for bi in bi_lst[begin_idx:] if bi.dir == target_dir),
                key=lambda bi: bi._low(),
                default=None,
            )
        else:
            target_dir = BI_DIR.UP
            end_bi = max(
                (bi for bi in bi_lst[begin_idx:] if bi.dir == target_dir),
                key=lambda bi: bi._high(),
                default=None,
            )

        if end_bi is None:
            return super().collect_left_as_seg(bi_lst)
        self.add_new_seg(bi_lst, end_bi.idx, is_sure=False, seg_dir=target_dir, reason="doubao_left_extreme")
