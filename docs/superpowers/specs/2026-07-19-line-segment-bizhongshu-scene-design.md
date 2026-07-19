# 线段划分——笔中枢场景下"同向更极端笔端点"规则设计

- 日期：2026-07-19
- 范围：`seg_algo = chan_v2`（`Seg/SegListChanV2.py`）
- 状态：设计已确认，待转实现计划

## 1. 背景与目标

线段端点确认中曾存在"同向更极端笔端点"作为候选端点替代来源，已于 commit `201bc2882`（2026-07-10）从 `SegListChanV2.py` 删除。删除后，底分型后更低向下笔、顶分型后更高向上笔不再替代当前候选端点。

实际并非所有情况都该删除该规则，而是**视场景而定**：当线段内出现满足约束的笔中枢场景时，使用同向更极端笔端点作为候选端点；其它场景仍使用"同类更极端特征分型"或"相反特征分型确认"的现有规则。

本设计在不改动 `ZS/ZS.py`、不影响其它 `seg_algo` 的前提下，为 `chan_v2` 有条件地重新引入同向更极端笔端点规则。

## 2. 关键定义

### 2.1 笔中枢（笔维度）

向上线段的笔中枢从**第一根向下笔**开始起算（向下线段对称：从第一根向上笔起算）。连续前三笔的重叠区间即中枢范围：

- 中枢下限 `low = max(前3笔低点)`
- 中枢上限 `high = min(前3笔高点)`
- 中枢范围 `[low, high]` 由前3笔**锁定**，后续笔进入中枢不改变 `low/high`
- 中枢外围低点 `peak_low = min(所涉及笔低点)`
- 中枢外围高点 `peak_high = max(所涉及笔高点)`（外围可由前3笔之后的笔产生）

### 2.2 向上/向下笔序列

`S` = 向上笔，`X` = 向下笔。向上线段：`S1 X1 S2 X2 ... Sn Xn`；向下线段对称。代码中以 `BI_DIR.UP/DOWN` 表示。

## 3. 命中场景（以向上线段为例，向下对称）

当向上线段中某向上笔 `Sn` 创段内新高（`Sn._high()` 高于段内此前所有向上笔高点）时，触发检测：扫描 `S1` 到 `Sn` 区间内的所有笔中枢，满足以下全部条件即命中：

1. 区间内至少存在 1 个笔中枢；
2. 每个笔中枢的笔数 ≤ 8 笔；
3. 若存在多个笔中枢，相邻两中枢的 `[peak_low, peak_high]` 区间不相交。

任一条件不满足即**不命中**，回落到现有特征分型规则（同类更极端特征分型 / 相反特征分型确认）。

### 3.1 笔中枢笔数

从进入中枢的第一笔（第一根向下笔）到**离开中枢的笔**（第一根 `[bi.low, bi.high]` 与前3笔重叠区间 `[low, high]` 不相交的笔）含两端的总数。若扫到 `Sn` 仍未离开，则该中枢**未闭合**，仍算中枢，`last_bi_idx = end_idx`，`bi_count = end_idx - first + 1`，仍受 ≤8 约束。

### 3.2 相邻中枢外围不相交

`peak_high_i < peak_low_{i+1}` 或 `peak_high_{i+1} < peak_low_i`。

## 4. 实现架构（方案 A：独立检测器 + V2 入口前置）

### 4.1 新增模块 `Seg/BiZSSceneDetector.py`

纯函数模块，不依赖 `ZS/ZS.py`，不修改既有中枢类。

```python
@dataclass
class BiZSInfo:
    first_bi_idx: int   # 进入中枢的第一笔（第一根反向笔）
    last_bi_idx:  int   # 离开中枢的笔（含）；未闭合时 = end_idx
    low: float          # 中枢下限 = max(前3笔低点)，锁定
    high: float         # 中枢上限 = min(前3笔高点)，锁定
    peak_low: float     # 外围低点 = min(涉及笔低点)
    peak_high: float    # 外围高点 = max(涉及笔高点)
    bi_count: int       # last - first + 1

@dataclass
class ZSSceneResult:
    zs_list: List[BiZSInfo]
    endpoint_bi_idx: int  # 候选终点 = [begin, end] 内同向极值笔索引

def detect_zs_scene(bi_list, begin_idx, end_idx, seg_dir) -> Optional[ZSSceneResult]:
    """
    向上段：中枢从向下笔起算，终点取区间内 _high() 最高的向上笔
    向下段：中枢从向上笔起算，终点取区间内 _low() 最低的向下笔
    未命中返回 None
    """
```

### 4.2 笔中枢构造算法（向上段为例）

1. 从 `begin_idx` 起找第一根向下笔作为中枢进入笔 `f`。
2. 取 `f, f+1, f+2`，若 `min(3笔高点) <= max(3笔低点)`（无重叠）→ 该处不构成中枢，从 `f+1` 起重新找下一根向下笔作进入笔。
3. 构成中枢：`low = max(前3笔低点)`、`high = min(3笔高点)`，锁定。
4. 向后扫描 `f+3, f+4, ...`，每笔 `[bi.low, bi.high]` 与 `[low, high]` 相交则留在中枢内，累计 `peak_low = min(...)`、`peak_high = max(...)`；第一根不相交的笔即离开笔 `l`，`bi_count = l - f + 1`。
5. 扫到 `end_idx` 都未离开 → 未闭合中枢，`last_bi_idx = end_idx`，`bi_count = end_idx - f + 1`。
6. 重复 1-5 找区间内所有笔中枢。

### 4.3 场景命中判定

- `zs_list` 非空；
- 每个 `bi_count <= 8`（任一超 8 即不命中）；
- 相邻两中枢 `[peak_low_i, peak_high_i]` 与 `[peak_low_{i+1}, peak_high_{i+1}]` 不相交；
- 满足全部 → 命中，`endpoint_bi_idx` = `[begin_idx, end_idx]` 内同向笔中极值笔（向上段取 `_high()` 最高，向下段取 `_low()` 最低）。
- 任一不满足 → 返回 `None`。

## 5. 与 `SegListChanV2.py` 的衔接

### 5.1 衔接点

放在 `treat_fx_eigen` 入口最前面（`SegListChanV2.py:465` 附近），拿到特征分型候选后、进入 `find_revert_fx` 之前：

```
treat_fx_eigen(fx_eigen, bi_lst):
    seg = self.seq_list[-1]
    begin_idx = seg.start_bi.idx
    cur_bi_idx = fx_eigen 对应当前笔

    if seg.is_zs_scene and not seg.is_sure:
        后移/回退处理（见 5.3）

    if 当前笔创新高(同向):
        res = detect_zs_scene(bi_lst, begin_idx, cur_bi_idx, seg.dir)
        if res is not None:                       # 命中
            self.add_new_seg(bi_lst, begin_idx, res.endpoint_bi_idx, is_sure=False)
            seg.is_zs_scene = True
            seg.eigen_fx / v2_notes 标记 kind="zs_scene"
            return                                # 跳过 same/reverse 事件

    # 未命中：回落现有 find_revert_fx / same / reverse 流程（不动）
```

### 5.2 命中即定、不走 same/reverse

命中后直接 `return`，不进入 `_collect_fx_events` 的 same/reverse 收集，避免双路径冲突。命中段 `is_sure=False`（未确认，可后移）。

### 5.3 未确认段后移（命中即定但可后移）

末段已是 `zs_scene` 命中段且未确认时，后续笔到来：

- **又创新高**（向上段：新高笔 `_high()` > `seg.end_bi._high()`）→ 重新 `detect_zs_scene(seg.start_bi.idx, cur_bi_idx, seg.dir)`：
  - 仍命中且终点变化 → 原地更新 `seg.end_bi = bi_lst[new_end]`（不动 `start_bi`），`return`。
  - 仍命中但终点不变 → 维持。
  - **场景失效**（返回 `None`，中枢超8笔 / 外围相交 / 无中枢）→ 清除 `seg.is_zs_scene`，回退为普通未确认段，重新进入特征分型 same/reverse 流程判定终点（终点可能不再是原同向极值笔）。
- **未创新高** → 维持当前未确认段，等后续。

### 5.4 转确认（`is_sure=True`）

沿用 V2 现有 reverse 规则：后续出现与段方向相反的特征分型且满足"相隔 ≥3 笔"确认条件 → 该 `zs_scene` 段确认，终点不变（即同向极值笔终点），随后开始新线段。复用 `SegListChanV2._event_has_three_bi` 等。

### 5.5 与现有机制兼容

- 命中段作为未确认段保留在 `seq_list` 末尾，`do_init` 删除末尾不确定段的现有行为不变。
- 命中段确认后，下一段 `start_bi` = 该段 `end_bi`，衔接由 `SegListComm` 现有逻辑保证。
- 后移/确认/回退全部发生在末段，与 `SegListComm.left_bi_break` 的"末段被突破"判定兼容。

## 6. 配置开关

`SegListChanV2` 内增加布尔开关，由 `seg_config` 传入：

- 配置项名：`chan_v2_zs_scene`（建议），默认 `True`（开启）。
- `False` 时跳过 4.x 全部逻辑，行为与 commit `201bc2882` 之后的 V2 完全一致，便于对照与回退。

## 7. 测试

### 7.1 单元测试 `Seg/test_bi_zs_scene_detector.py`

检测器为纯函数，用构造笔序列单测，无需 K 线：

- 3 笔重叠→1 中枢、≤8 笔 → 命中，终点 = 区间最高同向笔。
- 9 笔中枢 → 不命中。
- 2 中枢、外围区间相交 → 不命中。
- 2 中枢、外围区间分离 → 命中。
- 无重叠前3笔 → 不命中。
- 未闭合中枢（扫到 end 仍重叠）→ 命中。
- 向下线段镜像用例。
- 创新高笔远离中枢、终点取更早同向极值笔。

### 7.2 集成 / 回归

- 在现有 `chan_v2` 回归样本上跑，对比开关前 vs 后线段数与终点位置：不命中样本行为不变，仅命中段新增/后移。
- 绘图：`Plot/HtmlPlotDriver.py` 给 `zs_scene` 命中段加标注（参照 `201bc2882` 删除的 same_endpoint 标注位），便于肉眼核对。

## 8. 边界情况汇总

1. 区间内无中枢（前3笔无重叠 / 找不到第一根反向笔作进入笔）→ `None`，走特征分型。
2. 任一中枢超 8 笔 → `None`（非仅看最后一个）。
3. 相邻中枢外围区间相交 → `None`。
4. 单个中枢 → 无相邻判定，≤8 笔即命中。
5. 创新高笔远离中枢 → 终点取区间内最高同向笔，可能就是 Sn 或更早同向极值笔。
6. 向下/向上对称：检测器内 `is_up` 分支镜像，不写两份。
7. 未闭合中枢 → 算命中，`bi_count = end_idx - first + 1`，仍受 ≤8 约束。
8. 命中段确认后下段衔接由 `SegListComm` 保证。

## 9. 影响面

- 新增：`Seg/BiZSSceneDetector.py`、`Seg/test_bi_zs_scene_detector.py`。
- 修改：`Seg/SegListChanV2.py`（衔接点 + 后移/回退 + 配置开关）、`Plot/HtmlPlotDriver.py`（标注）、`ChanConfig.py`（默认开关）。
- 不动：`ZS/ZS.py`、`ZS/ZSList.py`、`Seg/EigenFX.py`、`Seg/Eigen.py`、默认 `chan`、`chan_doubao` 等。
