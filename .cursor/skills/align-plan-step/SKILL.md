---
name: align-plan-step
description: 在实现 docs/execution-plan.md 的某个 C 编号前做只读 Preflight，明确 Why、Boundary、Contract、修改半径和验收标准。当用户说“准备做 C6.1”“先对齐 C6.1”“实现下一个 commit”且尚未批准实现时使用。
---

# Align Plan Step

目标：让人类在代码生成前先掌握这次变更会如何改变系统。

**本 Skill 禁止写代码、修改文件、运行 formatter、生成 migration 或提交。**

## 1. 定位

- 用户给出 C 编号时直接使用。
- 未给编号时，用 git log 找最后一个 `Plan: Cx.y`，再从执行方案找到下一个适用 P0 条目。
- 读取该条目的内容、完成标准、引用的架构章节，以及 §0 中已经落地且不能回退的 contract。
- 检查同 Phase 前置 C 编号是否已落地。

## 2. 代码 Research

只读取与本条目存在直接数据流或 contract 关系的代码。不要为了“全面”扫描整个仓库。

至少确认：

- 上游调用方是谁；
- 下游消费者是谁；
- 数据 / 状态在哪里创建、转换、持久化；
- 已有 abstraction 能否复用；
- 哪些 deterministic 逻辑不能交给 LLM；
- 当前测试已经锁定了什么行为。

## 3. 输出 Preflight

固定输出：

### Why
这个 C 编号解决什么系统问题；缺失它时链路断在哪里。

### Before → After
用小型 Mermaid 或文本画出变更前后数据流。只新增本条目实际涉及的边。

### Change Radius
表格列出：
- 预计修改 / 新增文件；
- 每个文件为什么需要改；
- 明确 **NO-TOUCH** 的相邻模块。

### Contract / Invariant
列出新增、收紧、保持不变的 contract。特别标出安全、状态机、权限、source-of-truth、model boundary。

### Deterministic vs Model
明确哪些规则必须由代码保证，哪些内容可以让模型生成。

### Acceptance Evidence
把 execution-plan 的完成标准翻译成可执行测试：unit / integration / recorded model / manual。

### Human Review Set
最多 5 个文件，按 RED → YELLOW 排序，说明人类实现后重点看什么；GREEN 不占名额。

### Risks / Open Decisions
只有真正会改变工作量或 contract 的未决问题才列出。已有文档拍板的内容不要重新讨论。

最后必须输出：

```text
HUMAN GATE: WAITING
Implementation: NOT STARTED
Repository: UNCHANGED
```

然后停止。不要因为方案看起来明确就继续实现。
