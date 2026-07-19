import os
import unittest
from pathlib import Path

from Chan import CChan
from ChanConfig import CChanConfig
from Common.CEnum import AUTYPE, DATA_SRC, KL_TYPE


REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "TESTSEG_day.csv"


def _write_synthetic_csv(path: Path):
    """生成约 240 个交易日的合成日线：长期震荡上行，确保形成笔与线段。"""
    import datetime as _dt
    rows = []
    base = 10.0
    day = 0
    # 8 轮"上涨 ~12 天 + 回撤 ~7 天"，每轮高点抬升
    for cycle in range(8):
        peak = base + 6.0 + cycle * 4.0
        for _ in range(12):
            day += 1
            o = base + (peak - base) * (day % 12) / 12.0
            c = o + 0.4
            h = c + 0.8
            low = o - 0.6
            rows.append((day, o, h, low, c))
        base = peak
        trough = peak - 4.0 - cycle * 0.5
        for _ in range(7):
            day += 1
            o = peak - (peak - trough) * (day % 7) / 7.0
            c = o - 0.4
            h = o + 0.6
            low = c - 0.8
            rows.append((day, o, h, low, c))
        base = trough
    start = _dt.date(2024, 1, 1)
    with open(path, "w", encoding="utf-8") as f:
        for idx, (d, o, h, low, c) in enumerate(rows):
            date = (start + _dt.timedelta(days=idx)).isoformat()
            f.write(f"{date},{o:.4f},{h:.4f},{low:.4f},{c:.4f}\n")


class TestSegV2ZSSceneSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _write_synthetic_csv(CSV_PATH)

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(CSV_PATH)
        except FileNotFoundError:
            pass

    def _run(self, zs_scene: bool):
        config = CChanConfig({
            "seg_algo": "chan_v2",
            "chan_v2_zs_scene": zs_scene,
            "bi_strict": True,
            "bi_fx_check": "strict",
            "zs_combine": False,
        })
        chan = CChan(
            code="TESTSEG",
            data_src=DATA_SRC.CSV,
            lv_list=[KL_TYPE.K_DAY],
            config=config,
            autype=AUTYPE.NONE,
        )
        return chan

    def test_runs_with_zs_scene_on(self):
        chan = self._run(zs_scene=True)
        segs = chan.kl_datas[KL_TYPE.K_DAY].seg_list
        self.assertGreater(len(segs), 0)

    def test_runs_with_zs_scene_off(self):
        chan = self._run(zs_scene=False)
        segs = chan.kl_datas[KL_TYPE.K_DAY].seg_list
        self.assertGreater(len(segs), 0)

    def test_zs_scene_flag_propagates(self):
        chan_on = self._run(zs_scene=True)
        seg_list = chan_on.kl_datas[KL_TYPE.K_DAY].seg_list
        # 至少存在线段对象且 is_zs_scene 属性可读（True/False）
        for seg in seg_list:
            self.assertIn(seg.is_zs_scene, (True, False))


if __name__ == "__main__":
    unittest.main()
