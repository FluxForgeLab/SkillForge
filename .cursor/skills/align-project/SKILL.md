---
name: align-project
description: 只读当前代码、git 历史和权威文档，帮助人类开发者重建 SkillForge 的真实 Mental Model。当用户说“对齐项目”“我有点驾驭不住代码”“现在真实做到哪”“阶段切换前先梳理”时使用。
---

# Align Project

这是 **Human Alignment Audit**，不是代码任务。全程只读，禁止修改文件、重构、补测试或顺手修文档。

## 读取顺序

1. `AGENTS.md`、`docs/execution-plan.md` 的 §0 与当前 / 下一 Phase。
2. 最近 git log，确认真正 LANDED 的 C 编号。
3. 当前 Phase 对应 `docs/diagrams/*.json`；图只作为索引，结论必须回到真实代码。
4. 核心包：`domain`、当前 Phase、它的直接上下游，以及测试。
5. 只在发现冲突时补读架构设计相关章节。

## 必须回答

1. **Current State**：当前真实做到哪个 Phase / C 编号；区分 LANDED / PLANNED。
2. **Running Data Flow**：目前真正跑通的数据流，不把设计中的虚线说成已实现。
3. **Module Boundary**：核心模块的 responsibility / input / output / state / dependencies / failure boundary。
4. **Core Contracts**：当前最重要的 8–12 个 contract / invariant，并给出代码证据位置。
5. **Human Attention Map**：按 RED / YELLOW / GREEN 分类当前代码；解释为什么。
6. **Next Delta**：下一 Phase 接入后，哪些边和状态会新增，而不是泛泛介绍目标架构。
7. **Drift**：代码、README、diagram、execution-plan、AGENTS 之间的不一致；只报告，不修改。
8. **Reading Path**：最多 10 个文件，按阅读顺序写明“需要理解到实现级 / 接口级 / 行为级”。

## 输出格式

保持紧凑，固定为：

### 1. Current State
### 2. Landed Data Flow
### 3. Core Module Map
### 4. Core Contracts
### 5. RED / YELLOW / GREEN
### 6. Next Architecture Delta
### 7. Drift / Risks
### 8. Human Reading Path
### 9. Mermaid

Mermaid 最多 30 个节点，实线表示 LANDED，虚线表示 PLANNED。

结尾写：

`ALIGNMENT ONLY — repository unchanged`

不要开始下一条执行方案。
