# algo_test_agent

算法质量平台的**编排 Agent**：把「跑哪些场景、结果怎么判、和上次比是好是坏」从人的经验变成可执行、可复现、可观测的流程。

本地零依赖运行（只用 Python 标准库），所有外部平台通过 Adapter 接入，Mock 与真实实现同签名。

## 它能做什么

| 能力 | 一句话 | 入口 |
|---|---|---|
| **任务查询** | 给任务 id，返回结果 + 同场景历史 + 净影响（DiD） | Chat |
| **研发自测** | 给 commit，展开影响场景 → 预检 → 确认 → 执行 → 判读 | Chat / CLI |
| **趋势分析** | 给场景，按分布对比 + 双重差分给出可行动的结论 | Chat / CLI |

## 快速开始

```bash
# 1. 建样例数据（4 个场景 / 3 张图 / 12 次任务，含共享图与对照组）
python3 -m store.seed

# 2. 起 Web Chat
python3 -m web.server            # → http://127.0.0.1:8000

# 3. 或走 CLI
python3 agent/main.py --change "图A 召回算子改动" --scenario diff_fail

# 4. 测试
python3 -m unittest discover -s tests
```

## 架构

```
┌──────────────────────────────────────────────────┐
│ 入口    Web Chat（stdlib http） / CLI             │
├──────────────────────────────────────────────────┤
│ 能力    skills/  query · selftest · trend        │
├──────────────────────────────────────────────────┤
│ 上下文  context/ assembler · graph_scene · timeline│
│         （Task ↔ Change ↔ Graph ↔ Scene ↔ 历史）   │
├──────────────────────────────────────────────────┤
│ 编排    agent/   planner · executor · judge       │
├──────────────────────────────────────────────────┤
│ 工具    tools/   r2 · forcebot · diff · llm       │
├──────────────────────────────────────────────────┤
│ 数据    store/   SQLite：场景/图/变更/任务/快照/报告│
├──────────────────────────────────────────────────┤
│ 观测    observe/ tracer：traceId + span + 耗时     │
└──────────────────────────────────────────────────┘
```

**依赖方向**：`skills → context → store`，`agent → tools`。Skill 不允许直接查库。

## 目录

```
agent/     编排核心：规划 / 执行 / 判读 / 失败分级
context/   上下文聚合：场景↔图索引、历史时间线、DiD
skills/    三个能力 + 意图路由 + 卡片结构
store/     SQLite schema / 仓储 / 样例数据
observe/   trace（traceId + span，落库）
tools/     工具层（Mock 与真实同签名）
web/       Web Chat（stdlib 服务 + 原生 JS）
docs/      架构说明与 ADR
tests/     单测（17 个）
```

## 设计文档

- [架构说明](docs/architecture.md)
- [决策记录 ADR](docs/decisions.md) —— D1~D7，每条含「放弃了什么」

## 关键设计

1. **规则优先，模型兜底**（D1）
2. **执行与判读分离**（D2）—— 平台会换，判定标准不该跟着换
3. **失败分级处置**（D3）—— 可自愈的自愈、可判定的判死、剩下的交人
4. **Agent 不是门禁**（D4）—— webhook 管强制，chat 管探索
5. **Mock 与真实同签名**（D5）—— 换实现只改一个 import
6. **判读只信规则**（D6）—— 判错要命，说错只是难听
7. **阈值从机制推导**（D7）—— 1% 对应 ANN 近似误差，超了就是逻辑问题

## 边界

- 不是门禁：门禁必须由发布流程强制触发，Agent 只提供执行能力
- 不放行：判读结果只作为建议，最终放行由人签字
- 只做编排与判读，不重复造压测与 diff

## Roadmap

- [x] P1 数据层（SQLite）
- [x] P2 上下文聚合（场景↔图 / 历史 / DiD）
- [x] P3 观测（trace + span）
- [x] P4 三个 Skill
- [x] P5 Web Chat
- [ ] 接入真实平台 Adapter
- [ ] 权限与审计
- [ ] 评测集与回归（Eval Agent）
