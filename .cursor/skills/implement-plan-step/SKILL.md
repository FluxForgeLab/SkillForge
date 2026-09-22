---
name: implement-plan-step
description: 在 Human Gate 已通过后，按 docs/execution-plan.md 的一个 commit 编号完成实现、测试和验证。当用户在看过 align-plan-step 后明确批准实现，或明确要求跳过 Preflight 直接实现时使用。
---

# Implement Plan Step

## 0. Human Gate

实现前先判断：

- 当前会话已经对这个 C 编号执行过 `align-plan-step`，且用户之后明确批准 → 可以实现。
- 用户明确说“跳过对齐 / 直接实现 / 不需要 Preflight” → 可以实现，并在输出中标记 `Preflight: BYPASSED BY USER`。
- 其他情况 → **不要修改代码**，改用 `align-plan-step` 并停在 HUMAN GATE。

批准只对当前 C 编号有效，不自动延续到下一条。

## 1. 实现流程

```text
- [ ] 1. 再次定位条目：读 execution-plan 对应 C<x>.<y> 的内容与完成标准
- [ ] 2. 对照已批准 Preflight：确认 Change Radius / NO-TOUCH / Contract 没有漂移
- [ ] 3. 检查前置：同 Phase 更小编号是否已落地
- [ ] 4. 实现：只改批准范围；出现必须越界的依赖时停止并报告，不静默扩大范围
- [ ] 5. 测试：为完成标准写测试，修 bug 先写复现测试
- [ ] 6. 验证：运行 workflow-and-commits.mdc 规定的命令
- [ ] 7. 输出实现证据，不执行 git commit
```

## 2. Scope Drift

如果实现过程中发现 Preflight 有误，且需要：

- 修改 NO-TOUCH 文件；
- 改已有 Domain Contract / 状态机；
- 新增未对齐的 abstraction；
- 放宽权限 / policy；
- 改 execution-plan 的完成标准；

立即停止，把差异写成 `Preflight Delta`，等待用户重新批准。不要用“顺手重构”消化差异。

## 3. 输出

实现完成后只给：

- 已完成的 C 编号；
- 实际变更文件；
- 测试 / 验证结果；
- 与 Preflight 的偏差（没有则写 None）；
- 范围外发现；
- 建议的 commit message。

然后进入 `review-plan-step` 的审查阶段。**实现完成不代表可以提交。**

真正执行 `git commit` 必须遵守 `workflow-and-commits.mdc` 的 Human Commit Gate。
