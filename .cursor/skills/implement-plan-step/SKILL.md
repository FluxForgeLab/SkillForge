---
name: implement-plan-step
description: 按 docs/execution-plan.md 中的一个 commit 编号（如 C3.5）完成实现、测试、验证并给出 commit message。当用户说"做 C3.5"、"实现下一个 commit"、"继续执行方案"时使用。
---

# Implement Plan Step

## 流程

```text
- [ ] 1. 定位条目：读 docs/execution-plan.md §3 中的 C<x>.<y> 行，摘出"内容"与"完成标准"
- [ ] 2. 检查前置：同 Phase 内编号更小的条目是否已在 git log 中（grep "Plan: C<x>."）；缺失则先报告
- [ ] 3. 读相关设计章节：条目里引用的架构文档 § 号，以及 §0 审阅调整中相关的 R 编号
- [ ] 4. 实现：只改条目范围内的文件；新模块放规则 python-backend.mdc 的目录归属表指定位置
- [ ] 5. 测试：为完成标准写测试（unit 优先；需要 Docker 的标 integration）
- [ ] 6. 验证：跑 workflow-and-commits.mdc 中的提交前命令，全部通过
- [ ] 7. 输出：变更摘要 + 建议的 commit message（含 `Plan: C<x>.<y>`）+ 范围外发现的建议。不要执行 `git commit`，除非用户明确要求提交
```

## 用户没给编号时

运行 `git log --oneline | rg -o "C[0-9]+\.[0-9]+" | sort -V | tail -1` 找最后完成的编号，取执行方案中的下一条；若下一条标 **[opt]** 或 **[P1]** 且用户没要求，跳到下一个 P0 条目并说明。

## 条目本身有问题时

完成标准不可达、与安全红线冲突、或依赖未拍板决策：停止实现，在回复中给出具体冲突点和两种可行修改建议，等用户决定后再改 `docs/execution-plan.md`。不要静默改计划。

## spike 类条目

产出物是结论，不是代码。把测得的数字、决定和依据写进 commit body 与 `docs/deployment.md`（或条目指定的文档）。
