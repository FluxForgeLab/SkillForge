# DGX Spark 部署（C10.0 实测）

测量时间：2026-09-28，机器 `gx10-a430`（aarch64，NVIDIA GB10，驱动 580.142，统一内存 119Gi）。登录账号、地址和密码只在未入库的登录表里，不写进本文。

## 结论

选定 `nvidia/Qwen3.6-35B-A3B-NVFP4`。§0.7 的四条通过线都在这台机器上测过，没有改用 Nemotron。

| 通过线 | 结果 |
|---|---|
| 容器在 aarch64 上起来 | `nvcr.io/nvidia/vllm:26.08-py3` 中的 vLLM `0.27.1+93523f72.dev` 加载本地权重后，`Application startup complete`。容器 `OOMKilled=false`。 |
| `docker.inspect` 返回 OpenAI `tool_calls`，现有适配器能把点号工具名映射回来 | `finish_reason=tool_calls`，函数名 `docker_inspect`，参数 `{"service":"nginx"}`。`OpenAICompatibleAdapter` 映射为 `docker.inspect`。 |
| 单流 ≥ 10 tok/s，单步能放进现场演示 | 128 个 completion token 的墙钟 1.089s，合 117.6 tok/s。同一次工具调用墙钟 1.047s。 |
| API、网页、ops-lab 同时在跑时不 OOM | 三者与 vLLM 同时监听且健康检查为 200。主机 used 仍是 56Gi，available 63Gi。四个容器 `OOMKilled=false`，dmesg 没有 OOM 记录。 |

现场单次 live run 可以用这个模型。完整评测矩阵仍走已有的预计算 Benchmark 加一条 live run，不在现场跑完整矩阵。

Nemotron Nano 和 Nemotron Super 没有启动。原因是千问已经通过四条线，不是这两个模型失败。

## 镜像

手册配方写的是 `vllm/vllm-openai:latest`。这台机器访问 `registry-1.docker.io` 超时，没有改 `/etc/docker/daemon.json`。NGC 可以拉取。

| 镜像 | 结果 |
|---|---|
| `nvcr.io/nvidia/vllm:26.09-py3` | tag 不存在 |
| `nvcr.io/nvidia/vllm:26.02-py3` | 已拉下，21.9GB，vLLM 0.15.1，认不出 Qwen3.6 |
| `nvcr.io/nvidia/vllm:26.08-py3` | 采用。37.8GB，arm64，vLLM `0.27.1+93523f72.dev`。入口是 `nvidia_entrypoint.sh`，所以命令要写成 `vllm serve`，不能把模型名直接当容器参数 |

容器 CUDA 13.4（驱动 615.65.02）通过 forward compatibility 跑在内核驱动 580.142 上。日志有 `CUDA Forward Compatibility mode ENABLED`，引擎随后正常完成初始化。

## 权重

Hugging Face 的 xet 地址 `cas-bridge.xethub.hf.co` 在设置 `HF_HUB_DISABLE_XET=1` 后仍然超时或 401。ModelScope 上这个模型 id 的 API 返回 404。可用路径是 hf-mirror 的普通 HTTPS：`curl -fL -A skillforge-spike -C -` 下载到

```text
/home/asus_gx10/models/Qwen3.6-35B-A3B-NVFP4
```

目录约 22G，三个 safetensors 分片都在。服务时把这个目录只读挂进容器，并设置 `HF_HUB_OFFLINE=1`，避免引擎再去拉 xet。

## 启动命令

相对手册有三处按执行方案改过：上下文 32768 而不是 262144；`gpu-memory-utilization` 保持手册的 0.4；只绑定 `127.0.0.1:8000`，不把未鉴权的推理端口暴露到公网转发。`max-num-seqs` 在这次单流测量里设为 1。手册里的 flashinfer、marlin、MTP、fastsafetensors、chunked prefill、prefix caching 都开着，引擎已用这些后端完成加载。

```bash
docker run -d --name skillforge-vllm --gpus all --shm-size=16g \
  --restart no \
  -p 127.0.0.1:8000:8000 \
  -e HF_HUB_OFFLINE=1 \
  -e TRANSFORMERS_OFFLINE=1 \
  -e HF_HUB_DISABLE_XET=1 \
  -v "$HOME/models/Qwen3.6-35B-A3B-NVFP4:/model:ro" \
  nvcr.io/nvidia/vllm:26.08-py3 \
  vllm serve /model \
  --served-model-name nvidia/Qwen3.6-35B-A3B-NVFP4 \
  --host 0.0.0.0 \
  --port 8000 \
  --tensor-parallel-size 1 \
  --trust-remote-code \
  --kv-cache-dtype fp8 \
  --attention-backend flashinfer \
  --moe-backend marlin \
  --gpu-memory-utilization 0.4 \
  --max-model-len 32768 \
  --max-num-seqs 1 \
  --max-num-batched-tokens 8192 \
  --enable-chunked-prefill \
  --async-scheduling \
  --enable-prefix-caching \
  --speculative-config '{"method":"mtp","num_speculative_tokens":3,"moe_backend":"triton"}' \
  --load-format fastsafetensors \
  --reasoning-parser qwen3 \
  --tool-call-parser qwen3_xml \
  --enable-auto-tool-choice
```

日志时间：容器于 `2026-09-28T17:25:06Z` 之前的快照之后启动，`17:28:45` 打印 `Application startup complete`。

## 内存

启动前 `free -h`：used 3.9Gi，available 115Gi，swap 25Mi / 15Gi。磁盘 `/` 212G / 916G（25%，可用 658G）。

vLLM 自己的启动日志（统一内存记账，不能和下面的 `free` 相加）：

- 设备 119.63 GiB，`gpu-memory-utilization 0.4` 对应 47.85 GiB
- weights + non-torch 44.5 GiB
- KV cache 22.54 GiB
- CUDA graph 0.17 GiB

模型就绪后，以及 API、静态网页、ops-lab 同时在跑时，`free -h` 都是 used 56Gi、available 63Gi、swap 2.1Gi / 15Gi。buff/cache 从启动前的 98Gi 降到约 40Gi。swap 从 25Mi 升到 2.1Gi，发生在模型加载期间，栈加上去之后没有再涨。

`/metrics` 的 `process_resident_memory_bytes` 在测量当时是 `2172506112`（约 2.02GiB），这是 vLLM API 进程，不是引擎。文本指标里没有模型显存 gauge，`kv_cache_memory_bytes` 标签值是 `None`。`GET /api/model/status` 在 `openai_compatible` 时只把 `vllm:request_time_per_output_token_seconds` 的 count/sum 填进 `tokens_per_second`（进程启动后的累计均值）。没有样本或抓取失败时为 null。`memory_bytes` 保持 null，不用 API 进程 RSS 冒充模型内存。

同时在跑的测量进程：SkillForge API（`SKILLFORGE_MODEL_ADAPTER=fake`，`127.0.0.1:8010`）RSS 约 65MiB；网页是生产构建的 `http.server`（`127.0.0.1:5173`）RSS 约 19MiB。ops-lab 三个容器 healthy / running。测量结束后停掉了临时 API 和静态网页。vLLM 与 `skillforge-lab` 留在机器上。

ops-lab 的 `nginx:alpine` 和 `python:3.12-slim` 经 `docker.m.daocloud.io` 拉取后 tag 回原名。Docker Hub 超时，同样没有改 daemon 配置。

## 速度与工具调用

温度 0。三次请求的引擎计数：`generation_tokens_total=223`，`request_decode_time_seconds_sum=1.6445`，解码 135.6 tok/s。`inter_token_latency_seconds` 62 个样本、合计 1.6445s（MTP 一步可接受多个 token）。

| 请求 | 墙钟 | completion tokens | 结果 |
|---|---:|---:|---|
| 预热，`max_tokens=16` | 1.492s | 16 | 首包，10.7 tok/s |
| 单流，`max_tokens=128` | 1.089s | 128 | 117.6 tok/s |
| `docker_inspect`，`max_tokens=256` | 1.047s | 79 | `tool_calls`，75.5 tok/s |
| 栈仍在时再打一条，`max_tokens=32` | 0.329s | 32 | 97.3 tok/s，vLLM 仍返回 200 |

工具调用的 message 带 `tool_calls`，也带 `reasoning`。可见 `content` 为 null。适配器只读 `content` 和 `tool_calls`，不读 `reasoning`。Live Trace 不得展示 `reasoning`。

非工具回答会先把 completion 预算用在 `reasoning` 上。上面几条 `max_tokens` 较小的普通请求，`content` 长度都是 0，`finish_reason=length`。工具调用路径不受这个影响。后续接线要把 reasoning 留在适配器外，并给非工具回答留够 `max_tokens`，或者在请求里关掉思维链。不要把 `temperature=1` 套到这个模型上。

## 端口

这次测量里 vLLM 占 `127.0.0.1:8000`，临时 API 改到 `8010`，避免和本机开发默认的 API 端口冲突。仓库根目录 `docker-compose.yml` 的 `dgx` profile 把同一条命令的宿主机端口改到 `127.0.0.1:8001`，容器内仍是 8000，这样 SkillForge API 可以继续用 `127.0.0.1:8000`。网页 `127.0.0.1:5173`，ops-lab `8088`。推理服务不要绑到公网转发端口。权重目录用 `SKILLFORGE_VLLM_MODEL_DIR` 覆盖，默认是上面的本机路径。

```bash
docker rm -f skillforge-vllm
docker compose --profile dgx up -d
curl -sf http://127.0.0.1:8001/v1/models
```

## 回退

只有千问没通过上面四条时，才用同一 vLLM 镜像和同一组解析器改测手册矩阵里的 Nemotron Nano。2026-09-28 读到的矩阵列出 `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-BF16` 和 `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-FP8`，没有 `...-NVFP4` 这个句柄；NVFP4 出现在 Omni 系列。这两个 Nano 都没有在本次启动。Nano 也不合格才考虑 `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-NVFP4`。云端开发回退仍是现有 Kimi / Moonshot。
