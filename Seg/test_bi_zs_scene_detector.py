import unittest
from dataclasses import dataclass

from Common.CEnum import BI_DIR
from Seg.BiZSSceneDetector import detect_zs_scene


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
        self.assertEqual(res.zs_list[0].last_bi_idx, 4)
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

    def test_adjacent_zs_overlap_miss(self):
        # 两中枢外围区间相交 -> 不命中
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
        self.assertEqual(res.zs_list[0].last_bi_idx, 4)
        self.assertEqual(res.zs_list[1].first_bi_idx, 5)
        self.assertEqual(res.zs_list[1].last_bi_idx, 7)
        self.assertLess(res.zs_list[1].peak_high, res.zs_list[0].peak_low)
        self.assertEqual(res.endpoint_bi_idx, 6)  # X4 最低

    def test_too_few_bi_miss(self):
        seq = _seq([(True, 0, 10), (False, 5, 8)])
        self.assertIsNone(detect_zs_scene(seq, 0, 1, BI_DIR.UP))


if __name__ == "__main__":
    unittest.main()
