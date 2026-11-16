# evals/ —— Agent 行为评测

不是评模型能力，是**评 Agent 的执行轨迹**：它有没有照抄真值、有没有空转、有没有违反工具契约、状态有没有记错。

## 为什么用规则，不用模型

| | 规则判分 | LLM-as-judge |
|---|---|---|
| 可复现 | ✅ 同一 trace 永远同分 | ❌ 每次可能不同 |
| 成本 | 0 | 每次调用都花钱 |
| 能否单测 | ✅ | 难 |
| 覆盖面 | 只能判「可形式化」的 | 能判「语义合理」 |

**结论：能用规则的先用规则**（D6）。语义类判分（结论对不对）留给人工抽检，后续再考虑 rubric。

## 四个指标

| 指标 | 抓什么 | 判定 |
|---|---|---|
| `param_fidelity` | 工具实参是否来自真值集合 | = 1.0 |
| `redundant_call_rate` | 同 `(tool, args)` 重复调用比例 | = 0（可用 `repeat_allowance` 声明额度） |
| `contract_validity` | ID 类参数是否符合格式契约 | = 1.0 |
| `label_agreement` | `task_state` 与人工标注是否一致 | = 1.0 |

四条对应四类真实事故：参数幻觉、重试循环、契约错配、度量口径错误。

## 评测集结构

`dataset/cases.json`，每条：

```json
{
  "id": "E-001",
  "name": "参数幻觉：traffic_sign 编造",
  "truth":   {"traffic_sign": ["20260301-0001"]},
  "contract": {"graph_parse": {"graph_id": "^biz-\\d+$"}},
  "trace": {
    "task_state": "completed",
    "human_label": "completed",
    "tool_calls": [
      {"tool": "metric_query", "args": {"traffic_sign": "proj-live-001"}}
    ]
  }
}
```

- `truth`：字段 → 允许值集合。**没给真值的字段不判**，避免误杀
- `contract`：工具 → 字段 → 正则
- `trace`：一次 Agent 运行的实际轨迹

### 合法重复：`repeat_allowance`

同工具同参的重复默认一律算浪费（阈值 0）。轮询、幂等重查这类「本来就该重复」的调用，在 `trace` 里按工具名声明额度：

```json
{
  "trace": {
    "repeat_allowance": {"job_status": 4},
    "tool_calls": [
      {"tool": "job_status", "args": {"job_id": "T-001"}}
    ]
  }
}
```

`4` 表示该工具**同参最多出现 1+4 = 5 次**，第 6 次起才计入冗余。不写则额度为 0，行为与旧版一致。

注意额度是「按工具」而非「按调用」：只有能在 fixture 里说清为什么该重复时才声明，说不清的重复就该让它失败。

## 用法

```bash
python3 -m evals.runner                    # 跑批 + 对比基线
python3 -m evals.runner --update-baseline  # 更新基线
python3 -m evals.runner --update-baseline --force  # 允许把基线下调（默认拒绝）
python3 -m evals.runner --self-check       # 注入式验证：指标真的能发现问题吗
```

输出：

```
ID              参数保真       冗余率       契约      口径  案例
E-001  ❌        0.00      0.00    1.00    1.00  参数幻觉：traffic_sign 编造
...
汇总              0.83      0.11    0.83    0.83  pass_rate=0.33
基线              0.83      0.11    0.83    0.83  pass_rate=0.33  →0.00
```

## 门禁规则

`baseline.json` 存的是 `{pass_rate, metrics, n, dataset_sha}`，其中 `dataset_sha` 是 `cases.json` 的指纹。以下三种情况**退出码 1**：

| 情况 | 原因 |
|---|---|
| 基线文件缺失 | fail-closed：宁可拦住，也不假装通过 |
| `dataset_sha` 与当前数据集不符 | 基线只对生成它的那版 case 集有效，换数据集后旧数字不可比 |
| 未通过的 case 数比基线多 | 判分是确定性的（D6），不存在抖动，所以**不设百分比容差** |

判分确定性是关键前提：同一批 case 永远得同样的分。正因为如此，门禁以「未通过条数」比较而非 `pass_rate`，任何一条 case 由通过变失败都会拦住——早期的 5% 容差在 case 数 ≥ 20 时会吞掉单条退化。

`--update-baseline` 默认**只准变好**：`pass_rate` 低于现有基线时拒绝写入，需要显式加 `--force`。每次更新都是一次 git diff，退化必须在评审里被看见。

改了 `cases.json` 就必须跑一次 `--update-baseline`，否则下一次跑批会因指纹不符而失败。

## 自检（注入式验证）

一个指标最怕的是「永远满分」。所以 `--self-check` 会：

1. 复制 case
2. 把真值字段改成 `__HALLUCINATED__`
3. 断言 `param_fidelity` **必须下降**

下降 → 指标有效；不下降 → 指标是摆设。

## 怎么扩展

新增一个失败类型时：

1. 在 `dataset/cases.json` 加一条（含 trace 与 truth）
2. 如果是新的判分维度，在 `metrics.py` 加函数并登记到 `THRESHOLDS`
3. 跑 `--update-baseline` 生成新基线（数据集变了，旧基线会被指纹拦住）

新增一条 `truth` 字段时，**同时补一条能打它的负例**：`truth` 里写了但 trace 从没传过该字段的话，这个字段等于没校验。

## 已知边界

- 只覆盖**过程指标**，不判「结论对不对」——那需要人工抽检或 rubric
- trace 是离线导出的，接真实 Agent 时需要一层导出器
- 评测集只有 6 条，扩到 50 条以上才谈得上统计意义
