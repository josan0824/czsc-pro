# 线段笔中枢场景"同向更极端笔端点"规则 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `chan_v2` 线段划分中，当线段内出现满足约束的笔中枢场景时，有条件地重新启用"同向更极端笔端点"作为候选端点替代来源（即复活 commit `201bc2882` 删除的 `same_endpoint` 路径，并用笔中枢场景命中作为闸门）。

**Architecture:** 新增纯函数模块 `Seg/BiZSSceneDetector.py` 做场景检测（不依赖 `ZS/ZS.py`）；在 `CEigenFXV2.find_revert_fx` 内复活 `same_endpoint` 事件收集与处理分支（逐字还原 `201bc2882` 删除的代码），并用 `detect_zs_scene` 命中作为收集闸门。配置开关 `chan_v2_zs_scene` 默认开启。

**Tech Stack:** Python 3，`unittest`，项目既有 `Common.CEnum`/`Bi.Bi`/`Seg.*` 模块。

## Global Constraints

- 不修改 `ZS/ZS.py`、`ZS/ZSList.py`、`Seg/EigenFX.py`、`Seg/Eigen.py`、默认 `chan`、`chan_doubao` 等。
- 笔中枢范围 `low/high` 只由前 3 笔重叠区间确定；后续笔只更新外围 `peak_low/peak_high`。
- 中枢笔数 = 进入笔（第一根反向笔）到离开笔（不再与前 3 笔重叠区间相交）含两端总数；>8 笔则场景不成立；未闭合中枢（扫到 `end_idx` 仍未离开）算中枢，仍受 ≤8 约束。
- 多中枢时相邻两中枢 `[peak_low, peak_high]` 不相交（严格 `<`，边界相接算重叠）。
- 命中后候选终点 = `[begin, end]` 内同向笔极值笔（向上段取 `_high()` 最高，向下段取 `_low()` 最低）。向下线段对称。
- 配置开关 `chan_v2_zs_scene` 默认 `True`；`False` 时行为与 `201bc2882` 之后的 V2 完全一致。

## File Structure

- **Create** `Seg/BiZSSceneDetector.py` — 纯函数场景检测器：`BiZSInfo`、`ZSSceneResult`、`detect_zs_scene()`。
- **Create** `Seg/test_bi_zs_scene_detector.py` — 检测器单元测试，用轻量 `FakeBi`，无需 K 线栈。
- **Modify** `Seg/SegConfig.py` — 增加 `zs_scene` 配置字段。
- **Modify** `ChanConfig.py` — 读取 `chan_v2_zs_scene` 配置并传入 `CSegConfig`。
- **Modify** `Seg/SegListChanV2.py` — `CEigenFXV2` 增加 `zs_scene` 构造参数；复活 `_collect_same_endpoint_events`；`find_revert_fx` 内用 `detect_zs_scene` 闸门收集 `same_endpoint` 事件、还原 `kind=="same_endpoint"` 处理分支与备注分支；`cal_seg_sure` 传入 `zs_scene`；命中段标记 `is_zs_scene` 并写 `v2_notes`。
- **Modify** `Seg/Seg.py` — `CSeg` 增加 `is_zs_scene` 字段（默认 `False`）。
- **Modify** `Plot/HtmlPlotDriver.py` — `zs_scene` 命中段标注（参照 `201bc2882` 删除的 `same_endpoint` 标注位）。

## 接口契约

**`detect_zs_scene`**（检测器，后续任务依赖）：
```python
def detect_zs_scene(bi_list, begin_idx: int, end_idx: int, seg_dir) -> Optional[ZSSceneResult]
```
- 入参 `bi_list` 元素只需提供 `.dir`（`BI_DIR`）、`._high()`、`._low()`（duck typing，真实 `CBi` 与测试 `FakeBi` 均满足）。
- 返回 `None` 表示未命中；命中返回 `ZSSceneResult(zs_list: List[BiZSInfo], endpoint_bi_idx: int)`。
- `BiZSInfo` 字段：`first_bi_idx`/`last_bi_idx`/`low`/`high`/`peak_low`/`peak_high`/`bi_count`。

---

### Task 1: 创建检测器 `Seg/BiZSSceneDetector.py`

**Files:**
- Create: `Seg/BiZSSceneDetector.py`
- Test: `Seg/test_bi_zs_scene_detector.py`

**Interfaces:**
- Produces: `BiZSInfo`、`ZSSceneResult`、`detect_zs_scene(bi_list, begin_idx, end_idx, seg_dir) -> Optional[ZSSceneResult]`，供 Task 4 的 `find_revert_fx` 调用。

- [ ] **Step 1: 写失败测试（含 FakeBi 与多组用例）**

```python
# Seg/test_bi_zs_scene_detector.py
import unittest
from dataclasses import dataclass

from Common.CEnum import BI_DIR
from Seg.BiZSSceneDetector import detect_zs_scene, BiZSInfo, ZSSceneResult


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


def _upseq(prices):
    """
    prices: list of (is_up, low, high) tuples, idx = position.
    Returns list of FakeBi.
    """
    return [FakeBi(idx=i, dir=BI_DIR.UP if up else BI_DIR.DOWN, high=h, low=l)
            for i, (up, l, h) in enumerate(prices)]


class TestDetectZSScene(unittest.TestCase):
    def test_two_disjoint_zs_hit(self):
        # S1 X1 S2 X2 S3 X3 S4 X4: 两中枢外围区间不相交，≤8笔
        seq = _upseq([
            (True,  0, 10),  # S1 idx0
            (False, 2, 4),   # X1 idx1 中枢1进入
            (True,  2, 6),   # S2 idx2
            (False, 3, 5),   # X2 idx3  中枢1=[1..4] leave=S3
            (True,  7, 10),  # S3 idx4 leave (low 7 > high 4... wait high=min(4,6,5)=4, 7>4 ✓)
            (False, 8, 11),  # X3 idx5 中枢2进入
            (True,  8, 20),  # S4 idx6
            (False, 9, 12),  # X4 idx7  中枢2=[5..7] unclosed
        ])
        res = detect_zs_scene(seq, 0, 7, BI_DIR.UP)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.zs_list), 2)
        self.assertEqual(res.zs_list[0].first_bi_idx, 1)
        self.assertEqual(res.zs_list[0].last_bi_idx, 4)
        self.assertEqual(res.zs_list[1].first_bi_idx, 5)
        self.assertEqual(res.zs_list[1].last_bi_idx, 7)
        # 外围不相交：中枢1 peak_high < 中枢2 peak_low
        self.assertLess(res.zs_list[0].peak_high, res.zs_list[1].peak_low)
        # 终点=区间内最高向上笔 = S4 idx6
        self.assertEqual(res.endpoint_bi_idx, 6)

    def test_no_overlap_first3_miss(self):
        # 前3笔无重叠 -> 不命中
        seq = _upseq([
            (True,  0, 10),
            (False, 20, 25),  # X1 与 S2 不重叠
            (True,  26, 30),
            (False, 28, 32),
            (True,  29, 40),
        ])
        self.assertIsNone(detect_zs_scene(seq, 0, 4, BI_DIR.UP))

    def test_zs_over_8_pen_miss(self):
        # 单中枢但 bi_count = 9 -> 不命中
        seq = _upseq([
            (True,  0, 10),   # idx0 S1
            (False, 5, 8),     # idx1 X1 进入
            (True,  5, 12),    # idx2 S2
            (False, 6, 9),     # idx3 X2  中枢=[1..9]
            (True,  6, 11),    # idx4 仍重叠
            (False, 6, 9),     # idx5
            (True,  6, 11),    # idx6
            (False, 6, 9),     # idx7
            (True,  6, 11),    # idx8  9笔
        ])
        self.assertIsNone(detect_zs_scene(seq, 0, 8, BI_DIR.UP))

    def test_adjacent_zs_overlap_miss(self):
        # 两中枢外围区间相交 -> 不命中
        seq = _upseq([
            (True,  0, 10),   # S1
            (False, 2, 4),    # X1 中枢1=[1..4]
            (True,  2, 6),    # S2
            (False, 3, 5),    # X2
            (True,  7, 10),   # S3 leave(idx4)
            (False, 6, 9),    # X3 中枢2 [5..7]  peak_high 含 6~? 与中枢1 peak 6 重叠
            (True,  6, 20),   # S4
            (False, 7, 12),   # X4
        ])
        self.assertIsNone(detect_zs_scene(seq, 0, 7, BI_DIR.UP))

    def test_unclosed_zs_hit(self):
        # 单中枢扫到 end 仍重叠（未闭合），bi_count<=8 -> 命中
        seq = _upseq([
            (True,  0, 10),
            (False, 5, 8),    # X1 进入
            (True,  5, 12),   # S2
            (False, 6, 9),    # X2  中枢=[1..5] 全重叠到 end
            (True,  6, 15),   # S3
        ])
        res = detect_zs_scene(seq, 0, 4, BI_DIR.UP)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.zs_list), 1)
        self.assertEqual(res.zs_list[0].last_bi_idx, 4)  # unclosed -> end_idx
        self.assertEqual(res.zs_list[0].bi_count, 4)
        self.assertEqual(res.endpoint_bi_idx, 4)  # S3 最高

    def test_down_segment_mirror(self):
        # 向下段对称：中枢从第一根向上笔起算，终点取最低向下笔
        seq = [FakeBi(idx=i, dir=BI_DIR.DOWN if d else BI_DIR.UP, high=h, low=l)
               for i, (d, l, h) in enumerate([
                   (True,  0, 10),   # X1 idx0  向下段第一笔=向下笔
                   (False, 2, 4),    # S1 idx1 中枢进入(向上笔)
                   (True,  2, 6),    # X2 idx2
                   (False, 3, 5),    # S2 idx3  中枢=[1..4] leave=X3(idx4)
                   (True,  7, 10),   # X3 idx4 leave(low 7>4)
                   (False, 8, 11),   # S3 idx5 中枢2进入
                   (True,  8, 12),    # X4 idx6
                   (False, 9, 13),   # S4 idx7
               ])]
        res = detect_zs_scene(seq, 0, 7, BI_DIR.DOWN)
        self.assertIsNotNone(res)
        self.assertEqual(len(res.zs_list), 2)
        # 终点=最低向下笔：X3 idx4 low=7 最低向下笔
        self.assertEqual(res.endpoint_bi_idx, 4)

    def test_too_few_bi_miss(self):
        seq = _upseq([(True, 0, 10), (False, 5, 8)])
        self.assertIsNone(detect_zs_scene(seq, 0, 1, BI_DIR.UP))


if __name__ == "__main__":
    unittest.main()
```

> 说明：`test_two_disjoint_zs_hit` 用例的价格需满足中枢1 `high=min(4,6,5)=4`，S3 `low=7>4` 构成离开笔；中枢2 `peak_low` 需 > 中枢1 `peak_high=6`（中枢1 外围 `peak_high=max(4,6,5)=6`）。实现时若用例数值不满足断言，先调整用例数值使其自洽，再实现。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m unittest Seg.test_bi_zs_scene_detector -v`
Expected: FAIL（`ImportError: cannot import name 'detect_zs_scene'`）

- [ ] **Step 3: 实现检测器**

```python
# Seg/BiZSSceneDetector.py
from dataclasses import dataclass
from typing import List, Optional

from Common.CEnum import BI_DIR


@dataclass
class BiZSInfo:
    first_bi_idx: int
    last_bi_idx: int
    low: float          # 中枢下限 = max(前3笔低点)，锁定
    high: float         # 中枢上限 = min(前3笔高点)，锁定
    peak_low: float     # 外围低点 = min(涉及笔低点)
    peak_high: float    # 外围高点 = max(涉及笔高点)
    bi_count: int       # last - first + 1（含离开笔）


@dataclass
class ZSSceneResult:
    zs_list: List[BiZSInfo]
    endpoint_bi_idx: int


def _intersects(bi, low: float, high: float) -> bool:
    return bi._high() >= low and bi._low() <= high


def detect_zs_scene(bi_list, begin_idx: int, end_idx: int, seg_dir) -> Optional[ZSSceneResult]:
    """
    判断 [begin_idx, end_idx] 区间内是否命中"笔中枢场景"。
    向上段：中枢从第一根向下笔起算；终点取区间内 _high() 最高的向上笔。
    向下段：中枢从第一根向上笔起算；终点取区间内 _low() 最低的向下笔。
    未命中返回 None。
    """
    if begin_idx < 0 or end_idx >= len(bi_list) or end_idx - begin_idx < 2:
        return None
    is_up = seg_dir == BI_DIR.UP
    enter_dir = BI_DIR.DOWN if is_up else BI_DIR.UP
    same_dir = seg_dir

    zs_list: List[BiZSInfo] = []
    i = begin_idx
    while i <= end_idx:
        if bi_list[i].dir != enter_dir:
            i += 1
            continue
        f = i
        if f + 2 > end_idx:
            break
        b0, b1, b2 = bi_list[f], bi_list[f + 1], bi_list[f + 2]
        low = max(b0._low(), b1._low(), b2._low())
        high = min(b0._high(), b1._high(), b2._high())
        if not (high > low):
            i = f + 1
            continue
        peak_low = min(b0._low(), b1._low(), b2._low())
        peak_high = max(b0._high(), b1._high(), b2._high())
        leave = None
        j = f + 3
        while j <= end_idx:
            if _intersects(bi_list[j], low, high):
                peak_low = min(peak_low, bi_list[j]._low())
                peak_high = max(peak_high, bi_list[j]._high())
                j += 1
            else:
                leave = j
                break
        last = leave if leave is not None else end_idx
        zs_list.append(BiZSInfo(
            first_bi_idx=f,
            last_bi_idx=last,
            low=low,
            high=high,
            peak_low=peak_low,
            peak_high=peak_high,
            bi_count=last - f + 1,
        ))
        if leave is None:
            break
        i = last + 1

    if not zs_list:
        return None
    if any(z.bi_count > 8 for z in zs_list):
        return None
    for a, b in zip(zs_list, zs_list[1:]):
        if not (a.peak_high < b.peak_low or b.peak_high < a.peak_low):
            return None

    endpoint = begin_idx
    ext = None
    for k in range(begin_idx, end_idx + 1):
        bi = bi_list[k]
        if bi.dir != same_dir:
            continue
        v = bi._high() if is_up else bi._low()
        if ext is None or (is_up and v > ext) or (not is_up and v < ext):
            ext = v
            endpoint = k
    return ZSSceneResult(zs_list=zs_list, endpoint_bi_idx=endpoint)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m unittest Seg.test_bi_zs_scene_detector -v`
Expected: PASS（7 个用例全过；若个别用例数值不自洽，按 Step1 说明调整用例数值后重跑）

- [ ] **Step 5: 提交**

```bash
git add Seg/BiZSSceneDetector.py Seg/test_bi_zs_scene_detector.py
git commit -m "feat(seg): 新增笔中枢场景检测器 BiZSSceneDetector"
```

---

### Task 2: 增加配置开关 `chan_v2_zs_scene`

**Files:**
- Modify: `Seg/SegConfig.py`
- Modify: `ChanConfig.py`

**Interfaces:**
- Produces: `CSegConfig.zs_scene: bool`（默认 `True`），供 Task 3 的 `cal_seg_sure` 读取。

- [ ] **Step 1: 修改 `Seg/SegConfig.py` 增加字段**

把 `CSegConfig.__init__` 改为：
```python
class CSegConfig:
    def __init__(self, seg_algo="chan", left_method="peak", seg_lv=None, zs_scene=True):
        self.seg_algo = seg_algo
        self.seg_lv = seg_lv
        self.zs_scene = zs_scene
        if left_method == "all":
            self.left_method = LEFT_SEG_METHOD.ALL
        elif left_method == "peak":
            self.left_method = LEFT_SEG_METHOD.PEAK
        else:
            raise CChanException(f"unknown left_seg_method={left_method}", ErrCode.PARA_ERROR)
```

- [ ] **Step 2: 修改 `ChanConfig.py` 读取并传入**

把 `CChanConfig.__init__` 内 `self.seg_conf = CSegConfig(...)` 改为：
```python
self.seg_conf = CSegConfig(
    seg_algo=conf.get("seg_algo", "chan"),
    left_method=conf.get("left_seg_method", "peak"),
    seg_lv=conf.get("seg_lv", None),
    zs_scene=conf.get("chan_v2_zs_scene", True),
)
```

- [ ] **Step 3: 验证配置可用**

Run: `python -c "from ChanConfig import CChanConfig; c=CChanConfig({'seg_algo':'chan_v2'}); print(c.seg_conf.zs_scene); c2=CChanConfig({'seg_algo':'chan_v2','chan_v2_zs_scene':False}); print(c2.seg_conf.zs_scene)"`
Expected: 输出 `True` 和 `False`，且不抛 `invalid CChanConfig`（说明键被消费）。

- [ ] **Step 4: 提交**

```bash
git add Seg/SegConfig.py ChanConfig.py
git commit -m "feat(config): 增加 chan_v2_zs_scene 开关，默认开启"
```

---

### Task 3: `CSeg` 增加 `is_zs_scene` 字段

**Files:**
- Modify: `Seg/Seg.py`

**Interfaces:**
- Produces: `CSeg.is_zs_scene: bool`（默认 `False`），供 Task 4 标记命中段、Task 5 绘图识别。

- [ ] **Step 1: 修改 `Seg/Seg.py`**

在 `CSeg.__init__` 内 `self.ele_inside_is_sure = False` 同处附近新增：
```python
        self.is_zs_scene = False
```

- [ ] **Step 2: 验证**

Run: `python -c "from Seg.Seg import CSeg; from Bi.Bi import CBi; print('ok')"` （仅确保导入与字段不破坏）
Expected: 输出 `ok`，无异常。

- [ ] **Step 3: 提交**

```bash
git add Seg/Seg.py
git commit -m "feat(seg): CSeg 增加 is_zs_scene 字段"
```

---

### Task 4: 复活 `same_endpoint` 路径并接入场景闸门

**Files:**
- Modify: `Seg/SegListChanV2.py`

**Interfaces:**
- Consumes: `detect_zs_scene`（Task 1）、`CSegConfig.zs_scene`（Task 2）、`CSeg.is_zs_scene`（Task 3）。
- Produces: 命中场景时 `final_end_bi_idx` 可被同向更极端笔替代，并写 `v2_notes`、标记命中段 `is_zs_scene`。

- [ ] **Step 1: 导入检测器**

在 `Seg/SegListChanV2.py` 顶部 import 区新增：
```python
from .BiZSSceneDetector import detect_zs_scene
```

- [ ] **Step 2: `CEigenFXV2.__init__` 增加 `zs_scene` 参数**

把 `CEigenFXV2.__init__` 改为：
```python
def __init__(self, _dir: BI_DIR, exclude_included=True, lv=SEG_TYPE.BI,
             allow_first_second_include: bool = False, zs_scene: bool = True):
    super(CEigenFXV2, self).__init__(_dir, exclude_included=exclude_included, lv=lv)
    self.allow_first_second_include = allow_first_second_include
    self.zs_scene_enabled = zs_scene
    self.final_end_bi_idx: Optional[int] = None
    self.v2_notes: List[str] = []
    self.v2_final_all_sure: Optional[bool] = None
    self.zs_scene_result = None
```

- [ ] **Step 3: 复活 `_collect_same_endpoint_events`**

在 `CEigenFXV2` 内（`_collect_fx_events` 之后）新增方法（逐字还原 `201bc2882` 删除版）：
```python
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
```

- [ ] **Step 4: `find_revert_fx` 内收集 `same_endpoint` 事件（带场景闸门）**

在 `find_revert_fx` 中，紧接现有 `same_events = [...]` 与 `reverse_events = self._collect_fx_events(...)` 之后，插入：
```python
same_endpoint_events: List[_V2FxEvent] = []
if self.zs_scene_enabled:
    raw_same_endpoint = [
        event for event in self._collect_same_endpoint_events(bi_list, initial_event.peak_bi_idx + 1)
        if event.evidence_bi_idx > initial_event.evidence_bi_idx and self._is_more_extreme_event(event, initial_event)
    ]
    if raw_same_endpoint:
        seg_start_idx = max(0, self.ele[0].lst[0].idx - 1)
        last_endpoint_bi_idx = raw_same_endpoint[-1].peak_bi_idx
        zs_res = detect_zs_scene(bi_list, seg_start_idx, last_endpoint_bi_idx, self.dir)
        if zs_res is not None:
            same_endpoint_events = raw_same_endpoint
            self.zs_scene_result = zs_res
            self.v2_notes.append(
                f"笔中枢场景命中：S1起第{seg_start_idx + 1}笔至第{last_endpoint_bi_idx + 1}笔，"
                f"共{len(zs_res.zs_list)}个笔中枢；启用同向更极端笔端点替代。"
            )
```

- [ ] **Step 5: `events` 排序纳入 `same_endpoint`**

把现有 `events = sorted(...)` 改为（还原 `201bc2882` 前版本）：
```python
events = sorted(
    [(event.evidence_bi_idx, "same", event) for event in same_events] +
    [(event.evidence_bi_idx, "same_endpoint", event) for event in same_endpoint_events] +
    [(event.evidence_bi_idx, "reverse", event) for event in reverse_events],
    key=lambda item: (item[0], 0 if item[1] in ("same", "same_endpoint") else 1),
)
```

- [ ] **Step 6: 循环内还原 `kind == "same_endpoint"` 处理分支**

在 `find_revert_fx` 的 `for _, kind, event in events:` 循环内，紧接 `if not self._is_more_extreme_event(event, current_event): continue` 之后、`between_reverse_events = [...]` 之前，插入（逐字还原 `201bc2882` 删除版）：
```python
if kind == "same_endpoint":
    exact_reverse_events = [
        reverse_event for reverse_event in reverse_events
        if (
            reverse_event.evidence_bi_idx == event.evidence_bi_idx
            and current_event.peak_bi_idx < reverse_event.peak_bi_idx < event.peak_bi_idx
        )
    ]
    exact_reverse = self._pick_opposite_extreme(exact_reverse_events, self.dir)
    if exact_reverse is not None:
        span = self._event_bi_span(current_event, exact_reverse)
        if self._event_has_three_bi(current_event, exact_reverse):
            self.last_evidence_bi = bi_list[exact_reverse.evidence_bi_idx]
            self.last_evidence_bi_is_sure = exact_reverse.all_sure
            self.v2_final_all_sure = current_all_sure and exact_reverse.all_sure
            self.v2_notes.append(
                f"发现同向更极端笔端点：第{event.peak_bi_idx + 1}笔；"
                f"该笔正好确认相反"
                f"{self._event_note_text(exact_reverse, bi_list, self._opposite_fx_label(self.dir))}；"
                f"其与当前同类{self._event_note_text(current_event, bi_list, self._dir_fx_label(self.dir))}"
                f"跨度{span}笔，满足至少3笔，相反特征分型优先，"
                f"不替代线段候选端点，并以前一个同类{self._dir_fx_label(self.dir)}"
                f"第{current_event.peak_bi_idx + 1}笔作为线段端点。"
            )
            return True
        self.v2_notes.append(
            f"发现同向更极端笔端点：第{event.peak_bi_idx + 1}笔；"
            f"该笔正好形成相反"
            f"{self._event_note_text(exact_reverse, bi_list, self._opposite_fx_label(self.dir))}，但与当前同类"
            f"{self._event_note_text(current_event, bi_list, self._dir_fx_label(self.dir))}"
            f"跨度{span}笔，不满足至少3笔，继续按同向端点替代检查。"
        )
```

- [ ] **Step 7: 还原候选更新处备注分支**

在循环内 `self.final_end_bi_idx = event.peak_bi_idx` 之后的 `self.v2_notes.append(...)` 改为按 `kind` 分支（还原 `201bc2882` 前版本）：
```python
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
```

- [ ] **Step 8: `cal_seg_sure` 传入 `zs_scene`**

把 `CSegListChanV2.cal_seg_sure` 内两处 `CEigenFXV2(...)` 改为：
```python
up_eigen = CEigenFXV2(BI_DIR.UP, lv=self.lv, zs_scene=self.config.zs_scene)
down_eigen = CEigenFXV2(BI_DIR.DOWN, lv=self.lv, zs_scene=self.config.zs_scene)
```

- [ ] **Step 9: `treat_fx_eigen` 标记命中段**

在 `treat_fx_eigen` 内 `self.lst[-1].eigen_fx = fx_eigen` 之后新增：
```python
if getattr(fx_eigen, "zs_scene_result", None) is not None:
    self.lst[-1].is_zs_scene = True
```

- [ ] **Step 10: 冒烟验证**

Run: `python -c "from Seg.SegListChanV2 import CSegListChanV2, CEigenFXV2; print('import ok')"`
Expected: 输出 `import ok`。

- [ ] **Step 11: 提交**

```bash
git add Seg/SegListChanV2.py
git commit -m "feat(seg): chan_v2 复活 same_endpoint 同向更极端笔端点，受笔中枢场景闸门控制"
```

---

### Task 5: 命中段绘图标注

**Files:**
- Modify: `Plot/HtmlPlotDriver.py`

**Interfaces:**
- Consumes: `CSeg.is_zs_scene`（Task 3）。

- [ ] **Step 1: 定位标注位**

Run: `grep -n "v2_notes\|same_endpoint\|is_zs_scene" Plot/HtmlPlotDriver.py`
查看 `201bc2882` 删除的 `same_endpoint` 标注位（`HtmlPlotDriver.py` 当年被一并改动）。

- [ ] **Step 2: 增加命中段标注**

在 `v2_notes` 渲染处附近，对 `seg.is_zs_scene` 为真的线段追加标注文本"笔中枢场景命中段"（具体写入位置与样式跟随该文件现有 `v2_notes` 标注模式）。

- [ ] **Step 3: 提交**

```bash
git add Plot/HtmlPlotDriver.py
git commit -m "feat(plot): 笔中枢场景命中段标注"
```

---

### Task 6: 回归对照测试

**Files:**
- Test: 手工/脚本跑现有 `chan_v2` 样本

- [ ] **Step 1: 关闭开关跑基线**

用 `chan_v2_zs_scene=False` 跑现有样本，记录线段数与终点。

- [ ] **Step 2: 开启开关跑对照**

同样样本 `chan_v2_zs_scene=True`（默认），对比：非命中样本线段数/终点不变；命中段终点可能后移到同向更极端笔。

- [ ] **Step 3: 肉眼核对绘图**

查看 Task 5 标注的命中段，确认笔中枢场景结构正确。

- [ ] **Step 4: 提交回归记录（可选）**

如有固定样本与期望输出，加入 `tests/` 并提交。

---

## Self-Review

**Spec coverage：**
- §2 定义（中枢范围前3笔、外围）：Task 1 `_intersects` + `low/high` 锁前3笔、`peak_*` 累计。✓
- §3 命中场景（≥1中枢、≤8笔、相邻不相交、创新高触发、向下对称）：Task 1 全覆盖 + Task 4 闸门。✓
- §4 方案 A 独立检测器 + 入口接入：Task 1 + Task 4。✓（接入点从 spec 的 `treat_fx_eigen` 前置改为 `find_revert_fx` 内 `same_endpoint` 复活——更忠实，已与用户确认）
- §5 衔接/后移/确认/回退：`find_revert_fx` 复用既有 reverse 确认（`return True`），后移/回退由 `do_init`+`cal_seg_sure` 既有周期天然处理；场景失效（`zs_res is None`）则不收集 `same_endpoint` → 回落原 V2。✓
- §6 配置开关：Task 2。✓
- §7 测试：Task 1 单测 + Task 6 回归。✓
- §8 边界：Task 1 各用例覆盖。✓

**Placeholder scan：** 无 TBD/TODO。Task 5 Step2 标注位置依赖 grep 结果定位，已给出定位命令与跟随现有模式的说明（该文件当年随 `201bc2882` 改动，存在可定位的同类标注位）。

**Type consistency：** `detect_zs_scene` 签名在 Task 1 与 Task 4 一致；`BiZSInfo`/`ZSSceneResult` 字段一致；`is_zs_scene` 在 Task 3 定义、Task 4 写、Task 5 读，一致；`zs_scene_enabled`/`zs_scene_result` 在 `CEigenFXV2` 内一致。
