import unittest
from dataclasses import dataclass

from Common.CEnum import BI_DIR
from Seg.BiZSSceneDetector import detect_zs_breakout, detect_zs_scene


@dataclass
class FakeBi:
    idx: int
    dir: BI_DIR
    high: float
    low: float

    def _high(self): return self.high
    def _low(self): return self.low
    def is_up(self): return self.dir == BI_DIR.UP
    def is_down(self): return self.dir == BI_DIR.DOWN
    def get_end_val(self): return self.high if self.is_up() else self.low


def _seq(spec):
    """
    spec: list of (is_up, low, high). idx = position.
    向上段用：is_up=True 表示向上笔。
    """
    return [FakeBi(idx=i, dir=BI_DIR.UP if up else BI_DIR.DOWN, high=h, low=l)
            for i, (up, l, h) in enumerate(spec)]


def _seq_down(spec):
    """
    spec: list of (is_down, low, high). is_down=True 表示向下笔。
    """
    return [FakeBi(idx=i, dir=BI_DIR.DOWN if d else BI_DIR.UP, high=h, low=l)
            for i, (d, l, h) in enumerate(spec)]


class TestDetectZSScene(unittest.TestCase):
    def test_two_disjoint_zs_hit(self):
        # S1 X1 S2 X2 S3 X3 S4 X4：两中枢外围不相交，均 <=8 笔
        seq = _seq([
            (True,  0, 10),  # S1 idx0
            (False, 2, 4),   # X1 idx1 中枢1进入
            (True,  2, 6),   # S2 idx2
            (False, 3, 5),   # X2 idx3  中枢1=[1..4]，S3 离开
            (True,  7, 10),  # S3 idx4 离开（low7 > 中枢1 high4）
            (False, 8, 11),  # X3 idx5 中枢2进入
            (True,  8, 20),  # S4 idx6
            (False, 9, 12),  # X4 idx7  中枢2=[5..7] 未闭合
        ])
        res = detect_zs_scene(seq, 0, 7, BI_DIR.UP)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.zs_list), 2)
        self.assertEqual(res.zs_list[0].first_bi_idx, 1)
        self.assertEqual(res.zs_list[0].last_bi_idx, 3)  # 破坏笔(idx4)不计入
        self.assertEqual(res.zs_list[1].first_bi_idx, 5)
        self.assertEqual(res.zs_list[1].last_bi_idx, 7)
        self.assertLess(res.zs_list[0].peak_high, res.zs_list[1].peak_low)
        self.assertEqual(res.endpoint_bi_idx, 6)  # S4 最高

    def test_no_overlap_first3_miss(self):
        # 前 3 笔无重叠 -> 不命中
        seq = _seq([
            (True,  0, 10),
            (False, 20, 25),  # X1 与 S2 无重叠
            (True,  26, 30),
            (False, 28, 32),
            (True,  29, 40),
        ])
        self.assertIsNone(detect_zs_scene(seq, 0, 4, BI_DIR.UP))

    def test_zs_over_8_pen_miss(self):
        # 单中枢笔数 = 9（idx1..idx9）-> 不命中
        seq = _seq([
            (True,  0, 10),  # idx0 S1
            (False, 5, 8),   # idx1 X1 进入
            (True,  5, 12),  # idx2 S2
            (False, 6, 9),   # idx3 X2
            (True,  6, 11),  # idx4
            (False, 6, 9),   # idx5
            (True,  6, 11),  # idx6
            (False, 6, 9),   # idx7
            (True,  6, 11),  # idx8
            (False, 6, 9),   # idx9  bi_count=9
        ])
        self.assertIsNone(detect_zs_scene(seq, 0, 9, BI_DIR.UP))

    def test_zs_exactly_8_pen_hit(self):
        # 单中枢笔数 = 8（idx1..idx8），未闭合，<=8 -> 命中
        seq = _seq([
            (True,  0, 10),  # idx0 S1
            (False, 5, 8),   # idx1 X1 进入
            (True,  5, 12),  # idx2 S2
            (False, 6, 9),   # idx3 X2
            (True,  6, 11),  # idx4
            (False, 6, 9),   # idx5
            (True,  6, 11),  # idx6
            (False, 6, 9),   # idx7
            (True,  6, 15),  # idx8  bi_count=8
        ])
        res = detect_zs_scene(seq, 0, 8, BI_DIR.UP)
        self.assertIsNotNone(res)
        self.assertEqual(res.zs_list[0].bi_count, 8)

    def test_adjacent_zs_peak_overlap_but_lowhigh_disjoint_hit(self):
        # 两中枢 [peak_low,peak_high] 相接/相交，但 [low,high] 不重叠 -> 命中
        # （旧规则用外围判定会判为不命中；现规则改用中枢 low/high，更宽松）
        seq = _seq([
            (True,  0, 10),  # S1
            (False, 2, 4),   # X1 中枢1=[1..4]
            (True,  2, 6),   # S2
            (False, 3, 5),   # X2
            (True,  7, 10),  # S3 离开 idx4
            (False, 6, 9),   # X3 中枢2 peak 与中枢1 peak 重叠
            (True,  6, 20),  # S4
            (False, 7, 12),  # X4
        ])
        res = detect_zs_scene(seq, 0, 7, BI_DIR.UP)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.zs_list), 2)
        # 中枢1 [low=3, high=4]，中枢2 [low=7, high=9]：high4 < low7，不重叠
        self.assertLess(res.zs_list[0].high, res.zs_list[1].low)
        self.assertEqual(res.zs_list[0].first_bi_idx, 1)
        self.assertEqual(res.zs_list[0].last_bi_idx, 3)  # 破坏笔(idx4)不计入
        self.assertEqual(res.zs_list[1].first_bi_idx, 5)
        self.assertEqual(res.zs_list[1].last_bi_idx, 7)

    def test_adjacent_zs_lowhigh_overlap_miss(self):
        # 两中枢 [low,high] 重叠 -> 不命中（新规则的拒绝路径）
        seq = _seq([
            (True,  0, 10),   # S1
            (False, 5, 7),    # X1 中枢1进入
            (True,  5, 8),    # S2
            (False, 6, 9),    # X2  中枢1=[6,7]
            (True,  12, 15),  # S3 离开 idx4
            (False, 6, 8),    # X3 中枢2进入
            (True,  6, 9),    # S4
            (False, 6, 7),    # X4  中枢2=[6,7] 与中枢1 low/high 重叠
        ])
        self.assertIsNone(detect_zs_scene(seq, 0, 7, BI_DIR.UP))

    def test_unclosed_zs_hit(self):
        # 单中枢扫到 end 仍重叠（未闭合），<=8 -> 命中
        seq = _seq([
            (True,  0, 10),
            (False, 5, 8),   # X1 进入
            (True,  5, 12),  # S2
            (False, 6, 9),   # X2  中枢=[1..4] 全重叠到 end
            (True,  6, 15),  # S3
        ])
        res = detect_zs_scene(seq, 0, 4, BI_DIR.UP)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.zs_list), 1)
        self.assertEqual(res.zs_list[0].last_bi_idx, 4)
        self.assertEqual(res.zs_list[0].bi_count, 4)
        self.assertEqual(res.endpoint_bi_idx, 4)  # S3 最高

    def test_zs_overlap_low_uses_highest_low_not_peak_low(self):
        # 向上段前三笔 X1/S2/X2 的重叠下沿应取最高低点，即第三笔 X2 的低点；
        # 不能取三笔外围最低点。
        seq = _seq([
            (True,  0, 10),  # S1
            (False, 2, 9),   # X1
            (True,  2, 12),  # S2
            (False, 6, 11),  # X2，重叠下沿应为 6
            (True,  6, 15),  # S3
        ])
        res = detect_zs_scene(seq, 0, 4, BI_DIR.UP)
        self.assertIsNotNone(res)
        self.assertEqual(res.zs_list[0].low, 6)
        self.assertEqual(res.zs_list[0].peak_low, 2)
        self.assertEqual(res.zs_list[0].high, 9)

    def test_down_segment_mirror(self):
        # 向下段对称：中枢从第一根向上笔起算，终点取最低向下笔
        seq = _seq_down([
            (True,  15, 20),  # X1 idx0 向下段第一笔=向下笔
            (False, 12, 18),  # S1 idx1 中枢1进入（向上笔）
            (True,  10, 17),  # X2 idx2
            (False, 11, 16),  # S2 idx3  中枢1=[1..4]，X3 离开
            (True,  5, 9),    # X3 idx4 离开（high9 < 中枢1 low12）
            (False, 6, 9),    # S3 idx5 中枢2进入
            (True,  2, 8),    # X4 idx6
            (False, 3, 7),    # S4 idx7  中枢2=[5..7] 未闭合
        ])
        res = detect_zs_scene(seq, 0, 7, BI_DIR.DOWN)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.zs_list), 2)
        self.assertEqual(res.zs_list[0].first_bi_idx, 1)
        self.assertEqual(res.zs_list[0].last_bi_idx, 3)  # 破坏笔(idx4)不计入
        self.assertEqual(res.zs_list[1].first_bi_idx, 5)
        self.assertEqual(res.zs_list[1].last_bi_idx, 7)
        self.assertLess(res.zs_list[1].peak_high, res.zs_list[0].peak_low)
        self.assertEqual(res.endpoint_bi_idx, 6)  # X4 最低

    def test_too_few_bi_miss(self):
        seq = _seq([(True, 0, 10), (False, 5, 8)])
        self.assertIsNone(detect_zs_scene(seq, 0, 1, BI_DIR.UP))


class TestDetectZSBreakout(unittest.TestCase):
    def test_up_seg_down_bi_break_zd_hit(self):
        # 向上候选：中枢 ZD=6 ZG=8 last=4；其后向下笔 low<6 突破 ZD -> 命中
        seq = _seq([
            (True,  0, 10),   # idx0 S1
            (False, 5, 8),    # idx1 X1 中枢进入
            (True,  5, 12),   # idx2 S2
            (False, 6, 9),    # idx3 X2  中枢 ZD=6 ZG=8
            (True,  9, 15),   # idx4 S3 离开（low9>ZG8）last=4
            (False, 4, 7),    # idx5 X3 向下笔 low4<ZD6 -> 突破
        ])
        zs_res = detect_zs_scene(seq, 0, 4, BI_DIR.UP)
        self.assertIsNotNone(zs_res)
        bk = detect_zs_breakout(seq, zs_res.zs_list, BI_DIR.UP)
        self.assertIsNotNone(bk)
        self.assertEqual(bk.breakout_bi_idx, 5)
        self.assertEqual(bk.zs.low, 6)
        self.assertEqual(bk.zs.high, 8)

    def test_up_seg_no_break_miss(self):
        # 向下笔回到中枢内但未跌破 ZD -> None
        seq = _seq([
            (True,  0, 10),
            (False, 5, 8),
            (True,  5, 12),
            (False, 6, 9),    # 中枢 ZD=6 ZG=8
            (True,  9, 15),   # 离开 last=4
            (False, 6.5, 7),  # low6.5 未<6 -> 不突破
        ])
        zs_res = detect_zs_scene(seq, 0, 4, BI_DIR.UP)
        self.assertIsNotNone(zs_res)
        self.assertIsNone(detect_zs_breakout(seq, zs_res.zs_list, BI_DIR.UP))

    def test_down_seg_up_bi_break_zg_hit(self):
        # 向下候选对称：中枢 ZD=6 ZG=7 last=7；其后向上笔 high>7 突破 ZG -> 命中
        seq = _seq_down([
            (True,  15, 20),  # idx0 X1 向下段第一笔
            (False, 12, 18),  # idx1 S1 中枢进入（向上笔）
            (True,  10, 17),  # idx2 X2
            (False, 11, 16),  # idx3 S2
            (True,  5, 9),    # idx4 X3 离开（high9<ZD? 中枢 ZD=max(12,11,..) 待算）
            (False, 6, 9),    # idx5 S3 中枢2进入
            (True,  2, 8),    # idx6 X4
            (False, 3, 7),    # idx7 S4  中枢2 ZD=6 ZG=7 last=7
            (True,  1, 3),    # idx8 X5 继续向下（非向上笔，不触发）
            (False, 4, 10),   # idx9 S5 向上笔 high10>ZG7 -> 突破
        ])
        zs_res = detect_zs_scene(seq, 0, 7, BI_DIR.DOWN)
        self.assertIsNotNone(zs_res)
        last_zs = zs_res.zs_list[-1]
        self.assertEqual(last_zs.last_bi_idx, 7)
        bk = detect_zs_breakout(seq, zs_res.zs_list, BI_DIR.DOWN)
        self.assertIsNotNone(bk)
        self.assertEqual(bk.breakout_bi_idx, 9)
        self.assertEqual(bk.zs.high, 7)

    def test_empty_zs_list_miss(self):
        self.assertIsNone(detect_zs_breakout([], [], BI_DIR.UP))


class TestZSBreakoutConfirmFlow(unittest.TestCase):
    """规则四端到端数据流：中枢场景命中 -> 反向笔突破上一中枢 -> 反向中枢场景确认。

    复用 detect_zs_scene / detect_zs_breakout（均为 FakeBi 可用），验证
    _handle_zs_breakout 所依赖的判定链路：触发后反向线段经"中枢场景"命中。
    """

    def test_up_seg_breakout_then_reverse_zs_scene(self):
        # 向上段：中枢1 [ZD=17,ZG=19] last=4；b5 向下笔 low14<17 突破 ZD；
        # 其后 b6..b10 形成反向向下段中枢 [ZD=14,ZG=15] -> 反向中枢场景命中。
        seq = _seq([
            (True,  10, 20),  # idx0 S1
            (False, 16, 20),  # idx1 X1 中枢进入
            (True,  16, 19),  # idx2 S2
            (False, 17, 19),  # idx3 X2  中枢 ZD=17 ZG=19
            (True,  17, 22),  # idx4 S3 延伸中枢 last=4
            (False, 14, 22),  # idx5 X3 向下笔 low14<ZD17 -> 突破触发
            (True,  14, 16),  # idx6 S4 反向向下段第一笔(向上)
            (False, 12, 16),  # idx7 X4 反向中枢进入(向下)
            (True,  12, 15),  # idx8 S5
            (False, 11, 15),  # idx9 X6  反向中枢 ZD=14 ZG=15
            (True,  11, 14),  # idx10 S7
        ])
        # 1) 规则三：向上段中枢场景命中
        zs_res = detect_zs_scene(seq, 0, 4, BI_DIR.UP)
        self.assertIsNotNone(zs_res)
        self.assertEqual(zs_res.zs_list[-1].low, 17)
        self.assertEqual(zs_res.zs_list[-1].high, 19)

        # 2) 规则四触发：反向笔突破上一中枢 ZD
        bk = detect_zs_breakout(seq, zs_res.zs_list, BI_DIR.UP)
        self.assertIsNotNone(bk)
        self.assertEqual(bk.breakout_bi_idx, 5)

        # 3) 优先级1：反向中枢场景在 [breakout, end] 命中 -> 反向线段确认
        rev = detect_zs_scene(seq, bk.breakout_bi_idx, len(seq) - 1, BI_DIR.DOWN)
        self.assertIsNotNone(rev)
        self.assertGreaterEqual(rev.zs_list[-1].low, 14)
        self.assertLessEqual(rev.zs_list[-1].high, 15)


if __name__ == "__main__":
    unittest.main()
