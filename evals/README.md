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
| `redundant_call_rate` | 同 `(tool, args)` 重复调用比例 | = 0 |
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

## 用法

```bash
python3 -m evals.runner                    # 跑批 + 对比基线
python3 -m evals.runner --update-baseline  # 更新基线
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

`pass_rate` 低于基线 5 个百分点 → 退出码 1，可直接挂到 CI 上做门禁。

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
3. 跑 `--update-baseline` 生成新基线

## 已知边界

- 只覆盖**过程指标**，不判「结论对不对」——那需要人工抽检或 rubric
- trace 是离线导出的，接真实 Agent 时需要一层导出器
- 评测集只有 6 条，扩到 50 条以上才谈得上统计意义
