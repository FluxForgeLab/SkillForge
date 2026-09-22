---
name: review-plan-step
description: 在一个 C 编号实现完成后、提交前，只读真实 git diff 做 Architecture Delta Review。当用户说“review C6.1”“实现完了帮我对齐变化”“提交前审一下”时使用。
---

# Review Plan Step

这是 Human Control Loop 的提交前审查。默认只读：**不要修改代码，不要为了 review 通过而自动修问题。**

## 1. Evidence

- 读取该 C 编号的 execution-plan 条目与最近一次 Preflight。
- 默认审查 `git diff HEAD`（含 staged / unstaged）；若用户指定 commit，则审查指定 commit。
- 只根据真实 diff 下结论，不根据 Agent 自己的实现摘要。
- 读取受影响模块的关键测试，确认它们证明的是哪个 Contract。

## 2. 必须检查

### Scope
- 实际修改是否超出 Preflight Change Radius？
- 是否碰了 NO-TOUCH？
- 是否出现无关 refactor / abstraction？

### Architecture Delta
固定写：

```text
Before:
A → B

After:
A → C → B
```

如果没有架构变化，明确写 `Architecture Delta: NONE`，不要虚构。

### Contract Delta
逐项说明：
- API / schema；
- domain invariant；
- state；
- dependency direction；
- source of truth；
- permission / policy；
- failure boundary。

没有变化的项写 `unchanged`。

### Verification
把测试映射到 Contract，而不是只列“xx tests passed”。

### Human Review Set
最多 5 个文件：
- RED：建议逐段看什么；
- YELLOW：只需要核对哪些接口 / 失败模式；
- GREEN 不要求逐行 review。

### Drift
对比 Preflight，标记：
- `MATCH`
- `EXPLAINED DELTA`
- `UNAPPROVED DRIFT`

存在 `UNAPPROVED DRIFT` 时，不建议提交。

## 3. 输出结尾

二选一：

```text
HUMAN COMMIT GATE: READY FOR HUMAN REVIEW
Repository: UNCHANGED BY REVIEW
```

或：

```text
HUMAN COMMIT GATE: BLOCKED
Reason: <具体 drift / contract / verification 问题>
Repository: UNCHANGED BY REVIEW
```

即使 READY，也不要执行 commit；等待用户明确提交。
