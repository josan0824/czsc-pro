# 通达信本地缓存数据源（本地优先 + 联网兜底 + 写回）

- 日期：2026-07-10
- 状态：已批准，待实现计划

## 背景与动机

`web_server.py` 提供数据源「通达信历史数据」（`source=tdx_history`），由 `DataAPI/TdxHistoryAPI.py` 的 `CTdxHistory` 实现，只读本地通达信 `vipdoc` 二进制文件（`.day/.lc1/.lc5`）。它要求启动时通过 `TDX_HISTORY_DIR` 指向一个真实的通达信安装目录，且该目录须已用通达信客户端下载过历史数据。

当前用户既没有通达信安装目录，也没有任何历史数据，于是选择该数据源即抛：

```
未配置通达信历史数据目录。请设置 TDX_HISTORY_DIR 为包含 vipdoc 目录的通达信安装目录……
```

用户希望：

1. 程序自带一个长期默认目录（自动创建一个 `vipdoc`），无需手工配置。
2. 没有历史数据时，用通达信行情接口（`mootdx` 联网）把数据下载进去。
3. 调用逻辑：优先加载本地；本地不足则从网上获取，并写回本地，下次直接命中本地。

## 现状（不改动的部分）

- `DataAPI/MootdxAPI.py` 的 `CMootdx`：走通达信行情服务器**联网**拉 K 线，支持日 / 1m / 5m / 15m / 30m / 60m / 周 / 月，带分页与 `begin_date/end_date`，但不落盘。
- `DataAPI/TdxHistoryAPI.py` 的 `CTdxHistory`：只读本地 `vipdoc` 二进制，依赖 `mootdx.reader.Reader`（底层 `tdxpy.reader.*`），并对 15m/30m/60m 由 1m/5m 重采样。
- `web_server.py` 的 `custom:模块.类` 机制（见 `Chan.py:193`）：新增数据源只需新建 `DataAPI/xxx.py` 并在 `parse_source` 注册一行，不动框架。
- `main()` 已支持 `--tdx-history-dir` 参数与 `TDX_HISTORY_DIR` 环境变量。

## 设计

### 架构

新增一个混合数据源类 `CTdxCache`，复用现有两条通路：

- **读本地**：复用 `CTdxHistory` 基于 `Reader` 的读取与重采样。
- **联网兜底**：复用 `CMootdx` 拉缺口数据。
- **写回本地**：新增二进制写盘器，按核对过的 tdxpy 格式写 `.day/.lc1/.lc5`。

现有 `CMootdx`、`CTdxHistory` 不改动。

### 二进制格式（已核对自 `tdxpy.reader`）

- **`.day`**：32 字节/条，`struct "<IIIIIfII"` → 日期(int, YYYYMMDD)、开(int)、高(int)、低(int)、收(int)、成交额(float32)、量(int)、保留(int)。读取时按证券类型乘系数：
  - A 股 `[0.01, 0.01]`（OHLC raw = 价×100；量 raw = 手×100）
  - 指数 `[0.01, 1.0]`（OHLC raw = 价×100；量 raw 原值）
- **`.lc1` / `.lc5`**：32 字节/条，`struct "<HHfffffII"` → 日期(u16, `(年-2004)*2048 + 月*100 + 日`)、时间(u16, `时*60 + 分`)、开/高/低/收/额(float32 直存)、量(u32)、保留(u32)。无系数，写啥读啥。

### 组件

#### `DataAPI/tdx_vipdoc_io.py`（新）

纯函数模块，无网络、无状态：

- `classify_security_type(symbol, market) -> str`：按代码前缀判定证券类型（`SH_A_STOCK` / `SH_INDEX` / `SZ_A_STOCK` / `SZ_INDEX` 等），与 tdxpy `SECURITY_TYPE` 对齐，用于日线系数。
- `encode_day_rows(df, security_type) -> bytes`：把规范 DataFrame 编码成 `.day` 字节流（OHLC `round(价/系数[0])`，量 `round(量/系数[1])`，额 float32）。
- `encode_minute_rows(df) -> bytes`：编码成 `.lc1/.lc5` 字节流（float32 直存 OHLC/额，u32 量）。
- `write_day(path, df, security_type)` / `write_minute(path, df, suffix)`：**整文件重写**。读取既有文件（若有）→与新 df 按 `datetime` 去重合并（同时间戳取新值）→排序→整文件覆盖写。写前建文件父目录。
- `read_day(path, security_type) -> df` / `read_minute(path, suffix) -> df`：薄封装 tdxpy Reader，返回与 `CTdxHistory` 一致的规范列：`["datetime","open","high","low","close","amount","volume"]`。
- 写盘时用进程级文件锁（`fcntl` 或 `portalocker`）序列化对同一文件的并发写。

#### `DataAPI/TdxCacheAPI.py`（新）

`CTdxCache(CCommonStockApi)`，混合数据源：

- `__init__`、`SetBasciInfo`、`do_init`、`do_close`：参照 `CTdxHistory`，解析 `tdx_root`（复用 `resolve_tdx_history_root`）、`symbol/market`。
- `get_kl_data()`：实现下文「数据流」。
- 复用 `CTdxHistory.__resample_minutes` 的重采样逻辑（提取为可共享函数或直接调用同类静态方法）。

#### `web_server.py`（改）

- `main()`：若 `TDX_HISTORY_DIR` 既未由 `--tdx-history-dir` 设置、也未由环境变量提供，则默认设为 `<repo>/data/tdx`，并确保 `vipdoc/{sh,sz}/{lday,minline,fzline}` 子目录存在。
- `parse_source`：`tdx_history` 分支由 `custom:TdxHistoryAPI.CTdxHistory` 改为 `custom:TdxCacheAPI.CTdxCache`。
- `.gitignore`：加入 `data/tdx/`，不提交下载的市场数据。

### 数据流（每次请求）

```
请求(code, k_type, begin, end)
 ├ 1. 选后端原生级别:
 │     K_DAY  → .day (lday)
 │     K_1M   → .lc1 (minline)
 │     K_5M   → .lc5 (fzline)
 │     K_15M/K_30M/K_60M → 后端用 .lc1(1分钟)，读时重采样
 ├ 2. 读本地文件 → last_local_time（本地最后一根K线时间）
 ├ 3. 本地是否已覆盖 [begin, end]?
 │     是 → 不联网，直接用本地 df
 │     否 → 用 CMootdx 拉原生级别，begin_date = last_local_time
 │           （重拉最后一根以拾取当日修正）
 ├ 4. 本地 df + 联网 df 按 datetime 去重合并（同时间戳取联网新值）
 ├ 5. 写回: 整文件重写合并后全集（带文件锁，防并发写）
 ├ 6. 派生级别(15m/30m/60m): 用 1m 重采样
 └ 7. 按 begin/end 过滤 → yield CKLine_Unit
```

说明：

- 「本地覆盖 [begin, end]」对历史区间指 `last_local_time >= end`；对延伸到当前的请求，需联网拉增量（因为盘后才有新数据），仍走第 3 步。
- 派生级别（15m/30m/60m）的联网补齐总是拉 **1m**，写回 `.lc1`，再重采样，保证派生级别也能命中本地缓存。

### 错误处理

- 联网失败但本地有 → 用本地（可能略旧）+ 日志告警，不阻断画图。
- 本地无且联网失败 → 抛原 `CMootdx` 错误，UI 显示明确报错（与现状一致，不静默空数据）。
- 写盘失败 → 告警，仍用内存合并 df 出图（写回为「尽力而为」）。

### 测试（`tests/test_tdx_cache_api.py`）

- **写读回环**：合成 DataFrame → 写 `.day/.lc1/.lc5` → tdxpy 读回 → 值一致（float 容差内），分别覆盖 A 股与指数两套日线系数。
- **增量补齐**：预置旧数据文件，请求更晚范围 → mock `CMootdx`，断言只拉缺口、文件追加无重复时间戳、旧数据保留。
- **覆盖即跳过**：本地覆盖请求范围 → mock `CMootdx` 不被调用。
- **派生级别**：缓存 1m → 请求 15m/30m/60m → 重采样正确、不联网。
- **并发写**（可选）：两线程同时写同文件 → 文件锁保证最终一致、无损坏。

## 已知限制（设计内说明，不在本次解决）

- mootdx 单次联网约 8000 根上限 → 1 分钟首次最多约 33 个交易日；增量补齐随使用逐步前移。日线 8000 根 ≈ 32 年，足够。
- 本地缓存是通达信行情服务器返回的未复权数据；`autype != NONE` 时与现有 `CTdxHistory` 一致仅告警不复权。

## 不在范围内（YAGNI）

- 周/月线缓存（`CMootdx` 支持但 UI 当前级别选项不含；需要时再扩）。
- 北京交易所（BJ）股票（现有 `normalize_code` 支持但 `CTdxHistory` 仅处理 SH/SZ）。
- 自动定时后台补全（按需增量即可，不做定时任务）。
