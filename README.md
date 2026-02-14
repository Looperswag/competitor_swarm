# CompetitorSwarm

![Python](https://img.shields.io/badge/Python-3.10+-blue?logo=python)
![License](https://img.shields.io/badge/License-MIT-green)
![Status](https://img.shields.io/badge/Status-Active-success)

基于 **Swarm 模式** 的多 Agent 竞品分析系统，通过异构 Agent 协作实现多维度、深度的竞品分析。

---

## 📑 快速导航

| 章节 | 描述 |
|------|------|
| [快速开始](#-0-1-快速开始) | 5 步上手指南 |
| [Why CompetitorSwarm](#-为什么选择-competitorswarm) | 与传统工具对比 |
| [核心架构特点](#-核心架构特点) | Stigmergy、虚拟信息素等创新点 |
| [数据流动详解](#-数据流动详解) | 四阶段完整数据流 |
| [核心模块交互](#-核心模块交互) | 模块依赖关系图 |


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

**先检查环境**

```bash
python main.py check-env
```

预期至少应看到：

```text
✓ ZHIPUAI_API_KEY 已设置
✓ 配置文件加载成功
✓ 缓存目录可写
✓ 输出目录可写
✓ LLM 客户端初始化成功
```

**再执行分析**

```bash
python main.py analyze "Notion"
```

**预期输出**

```
[2026-xx-xx xx:xx:xx] 开始分析: Notion
[2026-xx-xx xx:xx:xx] Phase 1: 信息收集 (并行执行 4 个 Agent)
[2026-xx-xx xx:xx:xx]   🔍 侦察 Agent 完成
[2026-xx-xx xx:xx:xx]   🎨 体验 Agent 完成
[2026-xx-xx xx:xx:xx]   🔬 技术 Agent 完成
[2026-xx-xx xx:xx:xx]   📊 市场 Agent 完成
[2026-xx-xx xx:xx:xx] Phase 2: 交叉验证
[2026-xx-xx xx:xx:xx] Phase 3: 红蓝队对抗
[2026-xx-xx xx:xx:xx] Phase 4: 报告综合
[2026-xx-xx xx:xx:xx] 分析完成！耗时: XX 秒
[2026-xx-xx xx:xx:xx] 报告已保存到: output/analysis_Notion_xxxxxx.md
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

### 环境检查

```bash
python main.py check-env
```

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

## ✨ 为什么选择 CompetitorSwarm

| 维度 | 传统竞品分析工具 | CompetitorSwarm |
|------|------------------|-----------------|
| **分析深度** | 功能列表对比 | 多维度深度分析（产品/技术/市场/UX） |
| **分析视角** | 单一视角 | 红蓝队对抗 + 多 Agent 协作 |
| **时效性** | 依赖人工更新 | 实时网络搜索（Tavily + DuckDuckGo + Wikipedia） |
| **洞察质量** | 浅层信息 | 跨维度综合洞察（依赖数据质量与搜索可用性） |
| **自动化程度** | 手动收集资料 | 自动化多阶段分析（实际耗时受网络与重试影响） |
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

## 🧠 核心架构特点

### Stigmergy 通信机制

借鉴蚂蚁群体间接通信模式：
- Agent 通过共享环境（`StigmergyEnvironment`）传递信息
- 无需直接消息传递，降低耦合度
- 实现"涌现式智能"——整体洞察超越个体分析

### 虚拟信息素系统

高价值信号自动增强，低价值信号自然衰减：

```
强度组成 = 引用权重 + 验证权重 + 辩论权重 + 新鲜度权重
衰减机制: strength(t+1) = strength(t) × e^(-λt), λ=0.08
```

### 四阶段执行引擎

| 阶段 | 执行器 | 核心逻辑 |
|------|--------|----------|
| **Phase 1** | `ThreadPoolExecutor` | 并行信息收集（4 个维度 Agent） |
| **Phase 2** | `SemanticLinker` | 交叉验证（置信度 + 强度加权） |
| **Phase 3** | `DebateTranscript` | 红蓝对抗辩论（多轮裁决） |
| **Phase 4** | `Elite Agent` | 报告综合（涌现模式检测） |

### 多源搜索聚合

```
优先级排序: Tavily(100) → GitHub(50) → Wikipedia(20) → DuckDuckGo(10)

聚合模式:
├── priority: 按优先级顺序尝试，首个成功即返回
├── parallel: 并行请求所有源，合并结果
└── all: 依次请求所有源，完整聚合

特性: 自动去重 | 缓存支持 | 降级容错
```

### 语义关联引擎

跨维度信号自动关联（**无需 LLM 调用**）：
- 关键词重叠度计算
- 实体识别匹配
- 主题聚类分析

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

## 📊 数据流动详解

### 完整数据流图

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户输入                                      │
│              target="Notion" competitors=[] focus_areas=[]          │
└───────────────────────────────────┬─────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                     Coordinator (编排器)                             │
│              创建 run_id, 初始化 StigmergyEnvironment                │
└───────────────────────────────────┬─────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Phase 1: 信息收集 (ThreadPoolExecutor 并行)                         │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                   │
│  │ Scout   │ │Experience│ │Technical│ │ Market  │                   │
│  │ (产品)  │ │ (体验)   │ │ (技术)  │ │ (市场)  │                   │
│  └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘                   │
│       ↓           ↓           ↓           ↓                         │
│  ┌─────────────────────────────────────────────────────┐           │
│  │           MultiSourceSearchTool                      │           │
│  │    Tavily → DuckDuckGo → Wikipedia → GitHub         │           │
│  └─────────────────────────────────────────────────────┘           │
│       ↓                                                           │
│  SearchResult → Signal → StigmergyEnvironment.add_signal()        │
└───────────────────────────────────┬─────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Phase 2: 交叉验证                                                   │
│  ┌─────────────────────────────────────────────────────┐           │
│  │ SemanticLinker: 发现跨维度语义关联                    │           │
│  │ QuantitativeValidator: 验证数值数据                   │           │
│  │ - 置信度加权: 0.70                                   │           │
│  │ - 强度加权: 0.30                                     │           │
│  │ - 验证通过: +0.03 强度加成                           │           │
│  └─────────────────────────────────────────────────────┘           │
│       ↓                                                           │
│  Signal.verified = true, Signal.strength += 0.03                   │
└───────────────────────────────────┬─────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Phase 3: 红蓝对抗辩论                                               │
│  ┌─────────────────────────────────────────────────────┐           │
│  │ Round 1: RedTeam 攻击 → BlueTeam 防御               │           │
│  │ Round 2: RedTeam 反驳 → BlueTeam 再辩护             │           │
│  │ 裁决: LLM + 规则混合，调整 Signal.strength           │           │
│  └─────────────────────────────────────────────────────┘           │
│       ↓                                                           │
│  ClaimRecord(attack, defense, verdict) → DebateTranscript         │
└───────────────────────────────────┬─────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│  Phase 4: 报告综合                                                   │
│  ┌─────────────────────────────────────────────────────┐           │
│  │ Elite Agent:                                        │           │
│  │ - MotifMiner: 检测涌现模式(收敛/张力/桥接)           │           │
│  │ - 整合所有 Signal 和 Claim                          │           │
│  │ - 生成战略建议                                       │           │
│  └─────────────────────────────────────────────────────┘           │
│       ↓                                                           │
│  CoordinatorResult → Reporter → Markdown/HTML/JSON                │
└───────────────────────────────────┬─────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                        输出报告                                      │
│         output/analysis_{target}_{timestamp}.{md/html/json}        │
└─────────────────────────────────────────────────────────────────────┘
```

### 关键数据结构转换

| 阶段 | 输入 | 输出 | 关键转换 |
|------|------|------|----------|
| Phase 1 | `SearchQuery` | `Signal` | SearchResult → LLM → Signal |
| Phase 2 | `Signal` | `Verified Signal` | confidence/strength 加权评分 |
| Phase 3 | `Verified Signal` | `DebateResult` | Claim(adversarial/defensive) |
| Phase 4 | `All Signals` | `Report` | Motif + 综合洞察 |

---

## 🔗 核心模块交互

```
┌────────────────────────────────────────────────────────────────────┐
│                           CLI / Web API                            │
│                     main.py / src/web/app.py                       │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓
┌────────────────────────────────────────────────────────────────────┐
│                         Coordinator                                │
│                       src/coordinator.py                           │
│                    (四阶段执行引擎调度)                              │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓
┌────────────────────────────────────────────────────────────────────┐
│                       PhaseExecutor                                │
│                 src/core/phase_executor.py                         │
│    ┌──────────┬──────────┬──────────┬──────────┐                  │
│    │ Phase 1  │ Phase 2  │ Phase 3  │ Phase 4  │                  │
│    │ Collection│Validation│ Debate  │Synthesis │                  │
│    └──────────┴──────────┴──────────┴──────────┘                  │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓
┌────────────────────────────────────────────────────────────────────┐
│                    StigmergyEnvironment                            │
│                     src/environment.py                             │
│     ┌─────────────────────────────────────────────────────┐       │
│     │ Signal Graph │ Virtual Pheromone │ Handoff Queue   │       │
│     └─────────────────────────────────────────────────────┘       │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓
┌────────────────────────────────────────────────────────────────────┐
│                          Agents                                    │
│                        src/agents/                                 │
│  ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐ ┌───────┐     │
│  │Scout  │ │Exper- │ │Techni-│ │Market │ │RedTeam│ │BlueTeam│     │
│  │       │ │ience  │ │cal    │ │       │ │       │ │        │     │
│  └───┬───┘ └───┬───┘ └───┬───┘ └───┬───┘ └───────┘ └───────┘     │
│      └─────────┴─────────┴─────────┘                             │
│                         ↓                                         │
│              ┌─────────────────────┐                              │
│              │  Elite Agent 👑     │                              │
│              └─────────────────────┘                              │
└──────────────────────────────┬─────────────────────────────────────┘
                               ↓
┌────────────────────────────────────────────────────────────────────┐
│                     Supporting Systems                             │
│  ┌───────────────┐ ┌───────────────┐ ┌───────────────┐            │
│  │ Search System │ │ Analysis      │ │ Reporting     │            │
│  │ src/search/   │ │ src/analysis/ │ │ src/reporting/│            │
│  │               │ │               │ │               │            │
│  │ • Tavily      │ │ • Semantic    │ │ • HTML Gen    │            │
│  │ • DuckDuckGo  │ │   Linker      │ │ • Citation    │            │
│  │ • Wikipedia   │ │ • Motif Miner │ │   Manager     │            │
│  │ • GitHub      │ │ • Quantitative│ │ • Sections    │            │
│  └───────────────┘ └───────────────┘ └───────────────┘            │
└────────────────────────────────────────────────────────────────────┘
```

---

## 💡 核心创新点

| 创新点 | 描述 | 技术实现 |
|--------|------|----------|
| **Stigmergy 通信** | 借鉴蚂蚁群体间接通信，无需中心协调 | `StigmergyEnvironment` |
| **虚拟信息素** | 高价值信号自动增强，低价值信号衰减 | `PheromoneDecay` (λ=0.08) |
| **四阶段执行** | 结构化分析流程，确保洞察质量 | `PhaseExecutor` |
| **语义关联** | 跨维度信号自动关联（无 LLM 调用） | `SemanticLinker` |
| **涌现检测** | 检测收敛/张力/桥接模式 | `MotifMiner` |
| **红蓝对抗** | 批判性分析确保客观性 | `DebateTranscript` |
| **多源搜索** | 多数据源聚合，自动降级 | `MultiSourceSearchTool` |
| **量化验证** | 数值声明跨源验证 | `QuantitativeValidator` |


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


### Web API（长任务推荐异步）

- `POST /api/analyze`：兼容同步接口，成功返回报告链接；超时返回结构化 `504`。
- `POST /api/analyze/jobs`：创建后台分析任务，返回 `job_id`（推荐）。
- `GET /api/analyze/jobs/{job_id}`：查询任务状态（`queued/running/succeeded/failed/timed_out`）。

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


