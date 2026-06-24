from Bi.Bi import CBi
from Common.CEnum import BI_DIR, KLINE_DIR, SEG_TYPE

from .Eigen import CEigen
from .EigenFX import CEigenFX
from .SegConfig import CSegConfig
from .SegListChan import CSegListChan


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
