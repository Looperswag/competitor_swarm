# CompetitorSwarm

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Active-success)

基于 Swarm 模式的多 Agent 竞品分析系统，通过异构 Agent 协作实现多维度、深度的竞品分析。

---

## ✨ 为什么选择 CompetitorSwarm

| 维度 | 传统竞品分析工具 | CompetitorSwarm |
|------|------------------|-----------------|
| **分析深度** | 功能列表对比 | 多维度深度分析（产品/技术/市场/UX） |
| **分析视角** | 单一视角 | 红蓝队对抗 + 多 Agent 协作 |
| **时效性** | 依赖人工更新 | 实时网络搜索（Tavily + DuckDuckGo + Wikipedia） |
| **洞察质量** | 浅层信息 | **涌现洞察**（跨维度关联产生） |
| **自动化程度** | 手动收集资料 | 完全自动化，3-5 分钟生成报告 |
| **协作机制** | 无 | **Stigmergy 通信**（蚂蚁群体启发） |
| **信号追踪** | 无 | 结构化 Signal（置信度、强度、情感） |

---

## 🎯 项目背景

### 问题

传统竞品分析耗时耗力，容易遗漏关键信息，缺乏多维度深度洞察：
- 人工收集资料效率低，可能错过重要信息
- 分析视角单一，难以发现潜在威胁和机会
- 缺乏系统性方法论，分析质量不稳定
- 无法快速响应市场变化

### 解决方案

借鉴自然界蚂蚁群体的 **Stigmergy 通信机制**，设计多 Agent 协作系统：

- **异构 Agent**：7 种专业 Agent 各司其职，覆盖不同分析维度
- **间接通信**：通过共享环境实现 Agent 间协作，无需中心协调
- **虚拟信息素**：高价值发现自动传播和引用，形成"群体智慧"
- **红蓝对抗**：批判性分析与优势辩护，确保洞察的客观性

---

## 🏗️ Swarm 架构设计

### 核心概念映射

| Swarm 概念 | 竞品分析实现 |
|------------|-------------|
| 蚂蚁群体 | 异构 Agent（7 种类型） |
| 信息素轨迹 | 虚拟信息素（引用计数） |
| 间接通信 | Stigmergy 共享环境 |
| 群体智慧 | 涌现洞察 |
| 任务交接 | Handoff 机制 |

### 架构流程图

```
用户输入竞品需求
       ↓
┌──────────────────────┐
│   Coordinator        │
│   解析需求 → 分配任务  │
└──────────┬───────────┘
           ↓
┌─────────────────────────────────────────┐
│   Phase 1: 信息收集 (并行执行)           │
│   🔍 侦察 | 🎨 体验 | 🔬 技术 | 📊 市场 │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│   Phase 2: 交叉验证                      │
│   Agent 互相补充，Handoff 机制触发       │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│   Phase 3: 红蓝队对抗                    │
│   ⚔️ 红队 → 🛡️ 蓝队 → 反驳 (最多 3 轮)  │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│   Phase 4: 报告综合                      │
│   👑 精英 Agent 整合，生成最终报告       │
└────────────────┬────────────────────────┘
                 ↓
           输出结构化分析报告
```

### Agent 类型与职责

| Agent | 符号 | 维度 | 核心职责 | 输出示例 |
|-------|------|------|----------|----------|
| **Scout** | 🔍 | PRODUCT | 官网信息、定价、功能列表 | "Notion 提供免费版，付费版 $8/月" |
| **Experience** | 🎨 | UX | UI/UX、交互流程 | "移动端编辑体验较差" |
| **Technical** | 🔬 | TECHNICAL | 技术栈推测 | "前端使用 React，后端可能用 Node.js" |
| **Market** | 📊 | MARKET | 竞争格局、用户评价 | "G2 评分 4.5/5，用户称赞灵活性" |
| **RedTeam** | ⚔️ | - | 批判性分析 | "定价对小团队不友好" |
| **BlueTeam** | 🛡️ | - | 辩护性分析 | "高级功能物有所值" |
| **Elite** | 👑 | - | 综合洞察 | "建议推出针对小团队的轻量版" |

### Signal 数据结构

```python
Signal(
    signal_type: INSIGHT | THREAT | OPPORTUNITY | RISK | NEED
    dimension: PRODUCT | TECHNICAL | MARKET | UX | BUSINESS | TEAM
    confidence: 0.0-1.0      # 信息可靠性
    strength: 0.0-1.0        # 重要性（被引用次数增强）
    sentiment: POSITIVE | NEUTRAL | NEGATIVE
    actionability: IMMEDIATE | SHORT_TERM | LONG_TERM | INFORMATIONAL
)
```

---

## 🚀 0-1 快速开始

### 第一步：环境准备

**检查 Python 版本**

```bash
python --version  # 需要 3.10+
```

**进入项目目录**

```bash
cd competitor_swarm
```

**安装依赖**

```bash
pip install -r requirements.txt
```

### 第二步：获取 API Key

1. 访问 [智谱开放平台](https://open.bigmodel.cn/) 注册账号
2. 获取 API Key（格式类似：`xxxx.xxxxxx`）
3. （可选）获取 [Tavily](https://tavily.com/) API Key 用于实时搜索

### 第三步：配置项目

```bash
# 复制模板文件
cp .env.example .env

# 编辑 .env 文件
ZHIPUAI_API_KEY=你的API_Key
TAVILY_API_KEY=你的Tavily_Key  # 可选
```

### 第四步：第一次运行

```bash
python main.py analyze "Notion"
```

**预期输出**

```
[2024-xx-xx xx:xx:xx] 开始分析: Notion
[2024-xx-xx xx:xx:xx] Phase 1: 信息收集 (并行执行 4 个 Agent)
[2024-xx-xx xx:xx:xx]   🔍 侦察 Agent 完成
[2024-xx-xx xx:xx:xx]   🎨 体验 Agent 完成
[2024-xx-xx xx:xx:xx]   🔬 技术 Agent 完成
[2024-xx-xx xx:xx:xx]   📊 市场 Agent 完成
[2024-xx-xx xx:xx:xx] Phase 2: 交叉验证
[2024-xx-xx xx:xx:xx] Phase 3: 红蓝队对抗
[2024-xx-xx xx:xx:xx] Phase 4: 报告综合
[2024-xx-xx xx:xx:xx] 分析完成！耗时: XX 秒
[2024-xx-xx xx:xx:xx] 报告已保存到: output/analysis_Notion_xxxxxx.md
```

### 第五步：查看报告

```bash
# macOS
open output/analysis_Notion_*.md

# Linux
xdg-open output/analysis_Notion_*.md
```

---

## 📖 使用指南

### 基本分析

```bash
python main.py analyze "Notion"
```

### 对比分析

```bash
python main.py analyze "Notion" -c "飞书文档" -c "Wolai"
```

### 指定关注领域

```bash
python main.py analyze "Notion" -f "协作功能" -f "定价策略"
```

### 指定输出格式

支持 **4 种输出格式**：

```bash
# Markdown 格式（默认）
python main.py analyze "Notion"

# HTML 可视化报告
python main.py analyze "Notion" --format html

# JSON 数据格式
python main.py analyze "Notion" --format json

# 生成所有格式
python main.py analyze "Notion" --format all
```

### 保存报告

```bash
python main.py analyze "Notion" -o my_report.md
```

### 缓存管理

```bash
# 查看缓存状态
python main.py cache status

# 保存缓存
python main.py cache save filename.json

# 加载缓存
python main.py cache load filename.json

# 清除缓存
python main.py cache clear
```

---

## 🌟 实战案例

### 案例 1：SaaS 产品竞品分析

```bash
python main.py analyze "Notion" \
  -c "飞书文档" \
  -c "语雀" \
  -f "定价策略" \
  -f "协作功能" \
  -f "移动端体验" \
  -o notion_comparison.md
```

**输出解读**：重点对比三个产品在协作和定价上的差异

### 案例 2：移动应用竞品对比

```bash
python main.py analyze "印象笔记" \
  -c "Notion" \
  -c "Obsidian" \
  -f "同步机制" \
  -f "笔记格式" \
  -o apps_comparison.md
```

### 案例 3：开源项目调研

```bash
python main.py analyze "TiDB" \
  -c "CockroachDB" \
  -f "分布式架构" \
  -f "SQL 兼容性" \
  -o database_research.md
```

---

## 🔧 配置说明

### config.yaml

```yaml
model:
  name: "glm-4.7"              # 使用的模型
  temperature: 0.7              # 温度参数
  max_tokens: 4096              # 最大输出 token
  thinking_mode: true           # 思考模式

# 搜索配置
search:
  provider: "multi"             # 搜索提供商
  api_key: ""                   # 从环境变量 TAVILY_API_KEY 读取
  max_results: 10               # 每次搜索最大结果数

  # 多源搜索配置
  multi_source:
    aggregation_mode: "priority" # priority(优先)/parallel(并行)/all(全部)
    deduplication_enabled: true

  # 各搜索源配置
  providers:
    tavily:
      enabled: true
      priority: 100
    duckduckgo:
      enabled: true
      priority: 10
    wikipedia:
      enabled: true
      priority: 20

# Agent 结果数量配置
discovery_limits:
  min_per_agent: 15             # 每个 Agent 最少发现数量
  target_per_agent: 30          # 每个 Agent 目标发现数量
  max_per_agent: 50             # 每个 Agent 最大发现数量

cache:
  enabled: true                 # 启用缓存
  ttl: 3600                     # 缓存过期时间（秒）

scheduler:
  max_concurrent: 4             # 最大并发 Agent 数
  timeout: 600                  # 单个 Agent 超时（秒）
```

---

## 🧪 测试

```bash
# 运行所有测试
pytest

# 运行特定测试文件
pytest tests/test_environment.py

# 查看覆盖率
pytest --cov=src --cov-report=term-missing
```

---

## 📚 技术栈

- **语言**: Python 3.10+
- **LLM**: GLM API (glm-4.7)
- **并发**: asyncio
- **CLI**: Click
- **测试**: pytest

### 核心模块

```
src/
├── agents/          # 7 种 Agent 实现
├── schemas/         # Signal 数据结构
├── environment.py   # Stigmergy 共享环境
├── handoff.py       # Handoff 机制
├── coordinator.py   # 编排器
├── scheduler.py     # 调度器
└── reporter.py      # 报告生成器
```

---

## 💰 成本估算

使用 GLM-4.7 模型的参考成本：

- 输入: ¥0.5 / 1M tokens
- 输出: ¥2.0 / 1M tokens

**单次完整分析（7 个 Agent）估算：**
- 约 50K 输入 tokens
- 约 20K 输出 tokens
- 成本约 **¥0.065 / 次**

---

## 常见问题

### API 相关

**Q: 提示 "API Key 无效"**
- 检查 `.env` 文件中的 API Key 是否正确
- 确保没有多余空格或引号

**Q: 提示 "余额不足"**
- 单次分析成本约 ¥0.065
- 建议先充值 ¥10-50 进行测试

### 搜索功能

**Q: 搜索结果为空**
- 检查网络连接
- 确认 `TAVILY_API_KEY` 已配置
- 系统会自动降级使用内置搜索

### 性能问题

**Q: 分析时间过长**
- 正常情况下：简单分析 1-2 分钟，完整分析 3-5 分钟
- 可在 `config.yaml` 中降低 `target_per_agent` 数量

---

## 📄 License

MIT

---

<p align="center">
  <i>从 Swarm 智慧到商业洞察，让竞品分析进入自动化时代</i>
</p>
