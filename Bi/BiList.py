from typing import Any, Dict, List, Optional, Union, overload

from Common.CEnum import FX_TYPE, KLINE_DIR
from KLine.KLine import CKLine

from .Bi import CBi
from .BiConfig import CBiConfig


class CBiList:
    def __init__(self, bi_conf=CBiConfig()):
        self.bi_list: List[CBi] = []
        self.last_end = None  # 最后一笔的尾部
        self.config = bi_conf

        self.free_klc_lst = []  # 仅仅用作第一笔未画出来之前的缓存，为了获得更精准的结果而已，不加这块逻辑其实对后续计算没太大影响

    def __str__(self):
        return "\n".join([str(bi) for bi in self.bi_list])

    def __iter__(self):
        yield from self.bi_list

    @overload
    def __getitem__(self, index: int) -> CBi: ...

    @overload
    def __getitem__(self, index: slice) -> List[CBi]: ...

    def __getitem__(self, index: Union[slice, int]) -> Union[List[CBi], CBi]:
        return self.bi_list[index]

    def __len__(self):
        return len(self.bi_list)

    def try_create_first_bi(self, klc: CKLine) -> bool:
        for exist_free_klc in self.free_klc_lst:
            if exist_free_klc.fx == klc.fx:
                if self.is_better_same_fx(klc, exist_free_klc):
                    self.free_klc_lst.remove(exist_free_klc)
                    self.free_klc_lst.append(klc)
                    self.last_end = klc
                return False
            if self.can_make_bi(klc, exist_free_klc):
                self.add_new_bi(exist_free_klc, klc)
                self.last_end = klc
                return True
        self.free_klc_lst.append(klc)
        self.last_end = klc
        return False

    @staticmethod
    def is_better_same_fx(new_klc: CKLine, old_klc: CKLine) -> bool:
        if new_klc.fx == FX_TYPE.TOP:
            return new_klc.high >= old_klc.high
        if new_klc.fx == FX_TYPE.BOTTOM:
            return new_klc.low <= old_klc.low
        return False

    def update_bi(self, klc: CKLine, last_klc: CKLine, cal_virtual: bool) -> bool:
        # klc: 倒数第二根klc
        # last_klc: 倒数第1根klc
        flag1 = self.update_bi_sure(klc)
        if cal_virtual:
            flag2 = self.try_add_virtual_bi(last_klc)
            return flag1 or flag2
        else:
            return flag1

    def can_update_peak(self, klc: CKLine):
        if self.config.bi_allow_sub_peak or len(self.bi_list) < 2:
            return False
        if self.bi_list[-1].is_down() and klc.high < self.bi_list[-1].get_begin_val():
            return False
        if self.bi_list[-1].is_up() and klc.low > self.bi_list[-1].get_begin_val():
            return False
        if not end_is_peak(self.bi_list[-2].begin_klc, klc):
            return False
        if self[-1].is_down() and self[-1].get_end_val() < self[-2].get_begin_val():
            return False
        if self[-1].is_up() and self[-1].get_end_val() > self[-2].get_begin_val():
            return False
        return True

    def update_peak(self, klc: CKLine, for_virtual=False):
        if not self.can_update_peak(klc):
            return False
        _tmp_last_bi = self.bi_list[-1]
        self.bi_list.pop()
        if not self.try_update_end(klc, for_virtual=for_virtual):
            self.bi_list.append(_tmp_last_bi)
            return False
        else:
            if for_virtual:
                self.bi_list[-1].append_sure_end(_tmp_last_bi.end_klc)
            return True

    def update_bi_sure(self, klc: CKLine) -> bool:
        # klc: 倒数第二根klc
        _tmp_end = self.get_last_klu_of_last_bi()
        self.delete_virtual_bi()
        # 返回值：是否出现新笔
        if klc.fx == FX_TYPE.UNKNOWN:
            return _tmp_end != self.get_last_klu_of_last_bi()  # 虚笔是否有变
        if self.last_end is None or len(self.bi_list) == 0:
            return self.try_create_first_bi(klc)
        if klc.fx == self.last_end.fx:
            return self.try_update_end(klc)
        else:
            self.try_replace_last_end_before_opposite(klc)
        if self.can_make_bi(klc, self.last_end):
            self.add_new_bi(self.last_end, klc)
            self.last_end = klc
            return True
        elif self.update_peak(klc):
            return True
        return _tmp_end != self.get_last_klu_of_last_bi()

    def try_replace_last_end_before_opposite(self, opposite_klc: CKLine) -> bool:
        if len(self.bi_list) == 0 or self.last_end is None:
            return False
        replacement = self.find_better_same_fx_before_opposite(opposite_klc)
        if replacement is None:
            return False
        last_bi = self.bi_list[-1]
        if last_bi.end_klc.idx != self.last_end.idx:
            return False
        if not self.can_make_bi(opposite_klc, replacement):
            return False
        last_bi.update_new_end(replacement)
        self.last_end = replacement
        return True

    def find_better_same_fx_before_opposite(self, opposite_klc: CKLine) -> Optional[CKLine]:
        replacement = None
        current = self.last_end.next
        while current is not None and current.idx < opposite_klc.idx:
            if current.fx == self.last_end.fx and self.is_better_same_fx(current, self.last_end):
                can_make = self.can_make_bi(opposite_klc, current)
                if can_make:
                    replacement = current
            current = current.next
        return replacement

    def delete_virtual_bi(self):
        if len(self) > 0 and not self.bi_list[-1].is_sure:
            sure_end_list = [klc for klc in self.bi_list[-1].sure_end]
            if len(sure_end_list):
                self.bi_list[-1].restore_from_virtual_end(sure_end_list[0])
                self.last_end = self[-1].end_klc
                for sure_end in sure_end_list[1:]:
                    self.add_new_bi(self.last_end, sure_end, is_sure=True)
                    self.last_end = self[-1].end_klc
            else:
                del self.bi_list[-1]
        self.last_end = self[-1].end_klc if len(self) > 0 else None
        if len(self) > 0:
            self[-1].next = None

    def try_add_virtual_bi(self, klc: CKLine, need_del_end=False):
        if need_del_end:
            self.delete_virtual_bi()
        if len(self) == 0:
            return False
        if klc.idx == self[-1].end_klc.idx:
            return False
        if (self[-1].is_up() and klc.high >= self[-1].end_klc.high) or (self[-1].is_down() and klc.low <= self[-1].end_klc.low):
            # 更新最后一笔
            self.bi_list[-1].update_virtual_end(klc)
            return True
        _tmp_klc = klc
        while _tmp_klc and _tmp_klc.idx > self[-1].end_klc.idx:
            assert _tmp_klc is not None
            if self.can_make_bi(_tmp_klc, self[-1].end_klc, for_virtual=True):
                # 新增一笔
                self.add_new_bi(self.last_end, _tmp_klc, is_sure=False)
                return True
            elif self.update_peak(_tmp_klc, for_virtual=True):
                return True
            _tmp_klc = _tmp_klc.pre
        return False

    def add_new_bi(self, pre_klc, cur_klc, is_sure=True):
        self.bi_list.append(CBi(pre_klc, cur_klc, idx=len(self.bi_list), is_sure=is_sure))
        if len(self.bi_list) >= 2:
            self.bi_list[-2].next = self.bi_list[-1]
            self.bi_list[-1].pre = self.bi_list[-2]

    def satisfy_bi_span(self, klc: CKLine, last_end: CKLine):
        bi_span = self.get_klc_span(klc, last_end)
        if self.config.is_strict:
            return bi_span >= 4 or self.has_gap_break_bi(klc, last_end)
        uint_kl_cnt = 0
        tmp_klc = last_end.next
        while tmp_klc:
            uint_kl_cnt += len(tmp_klc.lst)
            if not tmp_klc.next:  # 最后尾部虚笔的时候，可能klc.idx == last_end.idx+1
                return self.has_gap_break_bi(klc, last_end)
            if tmp_klc.next.idx < klc.idx:
                tmp_klc = tmp_klc.next
            else:
                break
        return (bi_span >= 3 and uint_kl_cnt >= 3) or self.has_gap_break_bi(klc, last_end)

    def get_klc_span(self, klc: CKLine, last_end: CKLine) -> int:
        return klc.idx - last_end.idx

    def get_previous_bi(self, last_end: CKLine) -> Optional[CBi]:
        for bi in reversed(self.bi_list):
            if bi.end_klc.idx == last_end.idx:
                return bi
        return None

    def get_gap_break_info(self, klc: CKLine, last_end: CKLine) -> Optional[Dict[str, Any]]:
        if not self.config.gap_as_kl:
            return None
        previous_bi = self.get_previous_bi(last_end)
        return get_gap_break_info(previous_bi, last_end, klc)

    def get_gap_retrace_info(self, klc: CKLine, last_end: CKLine, for_virtual: bool = False) -> Optional[Dict[str, Any]]:
        if not self.config.gap_as_kl:
            return None
        previous_bi = self.get_previous_bi(last_end)
        return get_gap_retrace_info(previous_bi, last_end, klc, for_virtual=for_virtual)

    def has_gap_break_bi(self, klc: CKLine, last_end: CKLine) -> bool:
        # 有效破格缺口会豁免最小K线跨度；can_make_bi 中还会豁免分型区间重叠检查。
        return self.get_gap_break_info(klc, last_end) is not None

    def can_make_bi(self, klc: CKLine, last_end: CKLine, for_virtual: bool = False):
        gap_break_info = self.get_gap_break_info(klc, last_end)
        satisify_span = True if self.config.bi_algo == 'fx' else self.satisfy_bi_span(klc, last_end)
        if not satisify_span:
            return False
        if gap_break_info is None and not last_end.check_fx_valid(klc, self.config.bi_fx_check, for_virtual):
            return False
        if self.config.bi_end_is_peak and not end_is_peak(last_end, klc):
            return False
        return True

    def try_update_end(self, klc: CKLine, for_virtual=False) -> bool:
        def check_top(klc: CKLine, for_virtual):
            if for_virtual:
                return klc.dir == KLINE_DIR.UP
            else:
                return klc.fx == FX_TYPE.TOP

        def check_bottom(klc: CKLine, for_virtual):
            if for_virtual:
                return klc.dir == KLINE_DIR.DOWN
            else:
                return klc.fx == FX_TYPE.BOTTOM

        if len(self.bi_list) == 0:
            return False
        last_bi = self.bi_list[-1]
        if (last_bi.is_up() and check_top(klc, for_virtual) and klc.high >= last_bi.get_end_val()) or \
           (last_bi.is_down() and check_bottom(klc, for_virtual) and klc.low <= last_bi.get_end_val()):
            if not self.can_make_bi(klc, last_bi.begin_klc, for_virtual=for_virtual):
                return False
            if not last_bi.begin_klc.check_fx_valid(klc, self.config.bi_fx_check, for_virtual):
                return False
            last_bi.update_virtual_end(klc) if for_virtual else last_bi.update_new_end(klc)
            self.last_end = klc
            return True
        else:
            return False

    def get_last_klu_of_last_bi(self) -> Optional[int]:
        return self.bi_list[-1].get_end_klu().idx if len(self) > 0 else None


def end_is_peak(last_end: CKLine, cur_end: CKLine) -> bool:
    if last_end.fx == FX_TYPE.BOTTOM:
        cmp_thred = cur_end.high  # 或者严格点选择get_klu_max_high()
        klc = last_end.get_next()
        while True:
            if klc.idx >= cur_end.idx:
                return True
            if klc.high > cmp_thred:
                return False
            klc = klc.get_next()
    elif last_end.fx == FX_TYPE.TOP:
        cmp_thred = cur_end.low  # 或者严格点选择get_klu_min_low()
        klc = last_end.get_next()
        while True:
            if klc.idx >= cur_end.idx:
                return True
            if klc.low < cmp_thred:
                return False
            klc = klc.get_next()
    return True


def get_gap_break_info(previous_bi: Optional[CBi], last_end: CKLine, cur_end: CKLine) -> Optional[Dict[str, Any]]:
    if previous_bi is None:
        return None
    tmp_klc = last_end
    while tmp_klc and tmp_klc.idx < cur_end.idx:
        next_klc = tmp_klc.next
        if next_klc is None:
            return None
        if previous_bi.is_down():
            gap_value = next_klc.get_klu_min_low()
            if tmp_klc.get_klu_max_high() < gap_value and gap_value > previous_bi.begin_klc.high:
                return {
                    "direction": "up",
                    "prev_klc_idx": tmp_klc.idx,
                    "next_klc_idx": next_klc.idx,
                    "gap_value": gap_value,
                    "threshold": previous_bi.begin_klc.high,
                }
        elif previous_bi.is_up():
            gap_value = next_klc.get_klu_max_high()
            if tmp_klc.get_klu_min_low() > gap_value and gap_value < previous_bi.begin_klc.low:
                return {
                    "direction": "down",
                    "prev_klc_idx": tmp_klc.idx,
                    "next_klc_idx": next_klc.idx,
                    "gap_value": gap_value,
                    "threshold": previous_bi.begin_klc.low,
                }
        tmp_klc = next_klc
    return None


def get_gap_retrace_info(previous_bi: Optional[CBi], last_end: CKLine, cur_end: CKLine, for_virtual: bool = False) -> Optional[Dict[str, Any]]:
    if previous_bi is None:
        return None
    previous_gap = get_gap_break_info(previous_bi.pre, previous_bi.begin_klc, previous_bi.end_klc)
    if previous_gap is None:
        return None
    if previous_bi.end_klc.idx != last_end.idx:
        return None
    if previous_bi.is_down():
        if last_end.fx != FX_TYPE.BOTTOM:
            return None
        if for_virtual:
            if cur_end.dir != KLINE_DIR.UP:
                return None
        elif cur_end.fx != FX_TYPE.TOP:
            return None
    elif previous_bi.is_up():
        if last_end.fx != FX_TYPE.TOP:
            return None
        if for_virtual:
            if cur_end.dir != KLINE_DIR.DOWN:
                return None
        elif cur_end.fx != FX_TYPE.BOTTOM:
            return None
    else:
        return None
    return {
        "previous_bi_idx": previous_bi.idx,
        "previous_gap": previous_gap,
    }
