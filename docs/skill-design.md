# Skill 设计

这份说明描述**已经落地的 Skill 产物**。编译器的原始设想在设计文档 v0.1 §8.5、§8.6。和执行方案 §0.3、§0.4、§0.5 冲突时，以执行方案为准。golden 在 `skills/golden/service-recovery/`，它是 Runtime 和评测的契约，也是 Compiler 的验收参照。

## 一份 Skill 是什么

对业务来说，Skill 是从 Runbook 编译出来的操作能力：遇到什么症状、按什么顺序调用哪些工具、什么绝对不能做、怎样算恢复。对系统来说，它是一个目录，不是一段聊天提示。

落地的目录是：

```text
service-recovery/
├── SKILL.md
├── skill-card.md
├── scripts/
│   ├── diagnose.py
│   ├── recover.py
│   └── verify.py
├── references/
│   └── source-map.json
└── evals/
    └── evals.json
```

v0.1 §8.5 还列了 `tests/test_scripts.py` 和发布后的 `skill.oms.sig`。golden 里没有这两项。`BENCHMARK.md` 由评测写入版本目录，不是编译器的固定输出。静态校验允许的顶层名字是 `SKILL.md`、`skill-card.md`、`scripts/`、`references/`、`assets/`、`evals/`、`manifest.json`、`approver.txt`。多出来的路径会失败。

## SKILL.md

前置元数据至少有 `name` 和 `description`。`name` 是小写、数字和连字符，长度不超过 64，例如 `service-recovery`。`description` 不超过 1024 字符，写清做什么、在什么症状下用。还有 `version`、`triggers`、`tools`、`permissions`。

`tools` 使用带点的注册表名字：`docker.inspect`、`docker.logs`、`docker.restart`、`nginx.read_config`、`nginx.write_config`、`nginx.test`、`nginx.reload`、`http.get`。不要改成下划线。下划线只出现在发往模型 API 的那一层。

`permissions` 是默认沙箱策略的子集。`shell.destructive_commands` 不能是 true。编译结果放宽权限，静态校验应失败。

正文按场景来写，不解释 nginx 是什么。可执行指令以 `ins_NN` 开头。禁止项从 `ins_20` 起，和操作步骤分开。golden 的禁止项是：不删 volume，不动 mock-db，不用 `sudo`、`mount`、`shutdown`、`rm -rf`。

每个 `ins_NN` 必须出现在 `references/source-map.json`。条目指向知识从哪来：文档、sha256、页码或行号。`chunk_id` 每次重抽都会变，不能当作稳定坐标。没有出处的指令不能进入候选版本。这是 Evidence First，由校验代码执行，不交给模型判断。

## v0.1 和 v0.2

golden 就是 v0.1，不是一份已经包含全部修复的手册。

| | v0.1 | v0.2 |
|---|---|---|
| F1 backend 停了 | 检查并只重启 backend | 保留 |
| F2 upstream 被改成 `backend:8081` | 只把那一行改回 `server backend:8080;` | 保留 |
| F3 配置语法错误，reload 失败，端口也不对 | `evals.json` 里有这条 case，正文没有 `nginx -t`，也没有端口对照 | 补丁把 Appendix B 的步骤写进指令 |

F3 失败不是因为模型没发挥。Appendix B 在抽取时是 `diagnostic_rule`，触发词是 `nginx reload failed / upstream mismatch`。v0.1 的范围触发词是 `HTTP 502`、`backend unavailable`、`health check failed`，选不中它。失败分析用查询 `502 upstream nginx -t` 取前 3 条，必须召回标题含 Appendix B 的命中，然后补丁才把 `nginx -t` 写进 v0.2。

补丁可以改 `SKILL.md` 和 `scripts/`。不能改 `evals/evals.json` 的内容来让 case 变容易。不能放宽 permissions，不能删掉失败测试。v0.1 目录在补丁之后仍然不含 `nginx -t`；`nginx -t` 只出现在子版本里。

## 编译器分步做

对应 v0.1 §8.6。不要一次提示生成整个目录。

```text
Pass 1  解析知识
Pass 2  按 SkillSpec 的触发词划定范围
Pass 3  生成 SkillSpec
Pass 4  生成 SKILL.md
Pass 5  生成 scripts
Pass 6  生成 evals
Pass 7  静态校验
Pass 8  打包；校验通过才从 DRAFT 升到 CANDIDATE
```

Pass 2 故意选不中 Appendix B，这样 v0.1 才会在 F3 上失败，后面的进化才有确定的证据。不要为了让 v0.1 通过而把 Appendix B 写进第一次编译。

脚本只通过白名单函数操作 ops-lab，不 `import subprocess`，不 `import docker`。静态校验还会拒绝 `sudo`、`rm -rf`、`os.system`、`eval(`、`exec(`。脚本必须能通过 `py_compile`。

## 评测文件

`evals/evals.json` 的每条 case 有 id、任务、fixture、expected、forbidden 和超时。fixture 必须是 ops-lab 目录里的故障名：`backend_stopped`、`nginx_wrong_upstream`、`nginx_bad_config_reload`。expected 的键是 verifier 的字段。forbidden 用策略名，例如 `restart_database`、`delete_volume`，不是随便一句自然语言。

断言由代码执行。expected 的每个字段都要在 verifier 输出里出现且相等。forbidden 命中工具名或 `policy_violation` 的名字，这条 case 失败。

`record_candidate_evals` 把当时文件的 sha256 写入 `eval_seals`。升到候选不会自动写这枚封印。评测前若已有封印而文件变了，拒绝评测，并且不注入故障。补丁目录里的 evals 和封印不一致时，`reject_patched_evals` 拒绝。没有封印时评测仍可跑。

`uplift_pp` 是 Treatment 与 Control 成功率之差再乘 100。两臂同模型、同工具、同预算。设计叙述里的 1/3、2/3、3/3 是预计算对照，不是把 expected 改宽松之后的现场分数。

## 谁可以发布

静态校验通过，版本可以是候选。候选可以被评测，可以被打补丁，但不能当成已发布。

批准要有非空 approver，状态经过已验证再到已批准。发布只接受已批准的版本。进化任务的终点是候选或仍待校验的草稿。页面上的「批准」「发布」和 CLI 里的批准人参数都是人触发的。没有一条自动路径跳过它们。
