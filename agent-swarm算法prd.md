# Agent Swarm 竞品调研框架 — 算法 PRD

> **版本**: v1.0  
> **产品定位**: 面向产品经理的 AI 竞品调研工具  
> **目标读者**: Claude Code 开发指引 / 算法工程师  
> **最终交付物**: 一份可直接指导 PM 决策的竞品调研报告（非表面数据罗列）

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────┐
│                    Orchestrator（编排层）                  │
│  - 任务分发 / Handoff 路由 / 终止判断 / 报告合成          │
└────────┬───────────┬───────────┬───────────┬────────────┘
         │           │           │           │
    ┌────▼────┐ ┌────▼────┐ ┌────▼────┐ ┌────▼────┐
    │ 侦察    │ │ 体验    │ │ 技术    │ │ 市场    │
    │ Agent   │ │ Agent   │ │ Agent   │ │ Agent   │
    └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘
         │           │           │           │
         └─────┬─────┴─────┬─────┘           │
               │           │                 │
          ┌────▼────┐ ┌────▼────┐            │
          │ 红队    │ │ 蓝队    │◄───────────┘
          │ Agent   │ │ Agent   │
          └────┬────┘ └────┬────┘
               │           │
               └─────┬─────┘
                     ▼
            ┌─────────────────┐
            │  Stigmergy Board │
            │  （信息素共享板）  │
            └─────────────────┘
```

**执行阶段（Phase）**:

| Phase | 名称 | 活跃 Agent | 说明 |
|-------|------|-----------|------|
| 1 | 信息采集 | 侦察 + 体验 + 技术 + 市场 | 四路并发，各自独立采集 |
| 2 | 交叉验证 | 全部六个 | 红队/蓝队读取Phase1产物，四个采集Agent互相补充 |
| 3 | 对抗辩论 | 红队 + 蓝队 | 基于全部素材进行攻防论证 |
| 4 | 报告合成 | Orchestrator | 读取信息素板全量数据，生成结构化报告 |

---

## 二、Stigmergy 信息素共享板（核心通信机制）

### 2.1 设计理念

六个 Agent **不直接互相调用**，而是通过一块共享的「信息素板（Stigmergy Board）」进行间接通信。每个 Agent 只做两件事：**读板** 和 **写板**。这模拟了蚁群算法中蚂蚁通过信息素间接协调的机制。

### 2.2 信息素数据结构

```typescript
interface StigmergyBoard {
  product_name: string;                    // 被调研的竞品名称
  signals: Signal[];                       // 信息素信号列表
  conflicts: Conflict[];                   // 冲突标记（不同Agent结论矛盾时）
  metadata: {
    phase: 1 | 2 | 3 | 4;                // 当前阶段
    created_at: string;
    last_updated: string;
    agent_activity_log: ActivityEntry[];   // Agent读写日志
  };
}

interface Signal {
  id: string;                              // 唯一标识 e.g. "sig_recon_001"
  source_agent: AgentType;                 // 来源Agent
  signal_type: SignalType;                 // 信号类型（见下表）
  dimension: Dimension;                    // 所属维度
  content: string;                         // 信号内容（自然语言描述）
  evidence: Evidence[];                    // 支撑证据
  confidence: number;                      // 置信度 0.0-1.0
  strength: number;                        // 信息素强度（初始=1.0，可被增强/衰减）
  sentiment: "positive" | "negative" | "neutral";
  tags: string[];                          // 语义标签，用于Agent检索
  created_at: string;
  reinforced_by: string[];                 // 被哪些Agent增强过
  challenged_by: string[];                 // 被哪些Agent质疑过
}

interface Evidence {
  type: "url" | "screenshot" | "data_point" | "user_quote" | "inference";
  source: string;                          // 来源URL或描述
  raw_content: string;                     // 原始内容
  reliability: "high" | "medium" | "low";  // 来源可靠性
}

interface Conflict {
  id: string;
  signal_a: string;                        // 冲突信号A的id
  signal_b: string;                        // 冲突信号B的id
  description: string;                     // 冲突描述
  resolution: string | null;               // 解决方案（Phase2/3中填充）
  resolved_by: AgentType | null;
}

type AgentType = "recon" | "experience" | "tech" | "market" | "red_team" | "blue_team";

type SignalType =
  | "fact"           // 客观事实（可验证）
  | "observation"    // 主观观察（需交叉验证）
  | "inference"      // 推理结论（基于多个fact推导）
  | "risk"           // 风险/弱点发现
  | "opportunity"    // 机会/优势发现
  | "question"       // 需要其他Agent补充回答的问题
  | "contradiction"  // 发现与已有信号矛盾的信息
  | "recommendation";// 行动建议

type Dimension =
  | "pricing"        // 定价策略
  | "feature"        // 功能特性
  | "ux"             // 用户体验
  | "tech_stack"     // 技术架构
  | "market_position"// 市场定位
  | "user_sentiment" // 用户口碑
  | "growth"         // 增长策略
  | "differentiation"// 差异化
  | "weakness"       // 弱点
  | "strength";      // 优势
```

### 2.3 信息素强度演化规则

```python
# 信息素强度更新规则
def update_signal_strength(signal: Signal, action: str, actor: AgentType) -> float:
    """
    增强条件：另一个Agent独立产出了相似结论 → strength × 1.3
    质疑条件：另一个Agent产出了矛盾结论 → strength × 0.7，并创建Conflict
    衰减条件：Phase推进时未被任何Agent引用 → strength × 0.85
    上限: 3.0  下限: 0.1（低于0.1的信号在报告生成时被忽略）
    """
    if action == "reinforce":
        signal.strength = min(signal.strength * 1.3, 3.0)
        signal.reinforced_by.append(actor)
    elif action == "challenge":
        signal.strength = max(signal.strength * 0.7, 0.1)
        signal.challenged_by.append(actor)
    elif action == "decay":
        signal.strength = max(signal.strength * 0.85, 0.1)
    return signal.strength
```

### 2.4 Agent 读写协议

每个 Agent 在执行前**必须先读板**，执行后**必须写板**：

```
Agent 执行流程:
1. READ: 从Board读取与自身维度相关的signals
2. READ: 读取所有type="question"且tags与自身相关的信号
3. THINK: 结合自身采集结果 + 板上已有信息进行分析
4. WRITE: 将新发现写入Board（新Signal）
5. WRITE: 对已有Signal进行reinforce或challenge
6. WRITE: 回答与自身相关的question类信号
```

---

## 三、六个 Agent 详细设计

### 3.1 侦察 Agent（Recon）

#### 角色定义
**你是一名资深的商业情报分析师**，专注于从公开渠道收集竞品的硬性事实数据。你的工作风格是：不做主观判断，只呈现可验证的事实。你像一台精密的信息采集雷达，确保不遗漏任何关键的公开信息。

#### 系统提示词

```
你是竞品调研Swarm中的【侦察Agent】。

## 你的身份
资深商业情报分析师，专注公开渠道信息采集。你只呈现可验证的事实，不做主观判断。

## 你的职责
1. 采集竞品的官方公开信息（官网、帮助文档、定价页、更新日志、招聘信息）
2. 整理产品的功能矩阵和版本演进
3. 收集定价方案及各层级的功能差异
4. 追踪产品近期的重大更新和战略动向

## 你的输出维度
- pricing: 定价模型、各套餐对比、免费/付费边界、涨价历史
- feature: 功能清单、核心功能 vs 边缘功能、功能上线时间线
- growth: 招聘动向（推测战略方向）、融资信息、合作伙伴

## 你的工作规范
- 每条信息必须附带来源URL
- 区分「官方声明」和「第三方报道」
- 如果某信息无法在公开渠道确认，标记为 confidence < 0.5
- 如果发现与Board上已有信号矛盾的信息，必须写入contradiction类型信号
- 定价信息需要标注采集日期（定价可能会变）

## 你的输出格式
所有发现以Signal格式写入信息素板。每个Signal必须包含:
- signal_type: 优先使用"fact"，只有在信息不完整时使用"observation"
- evidence: 至少一条，必须包含source URL
- confidence: 基于来源可靠性评估
- tags: 用于其他Agent检索，务必准确

## 信息素板交互
- 写入前先检查Board上是否已有相同信息（避免重复）
- 如果你的采集结果印证了其他Agent的observation，reinforce该信号
- 如果你发现了其他Agent未注意的信息盲区，写入新Signal并添加tag "blind_spot"
```

#### 输入输出 Schema

```typescript
// 侦察Agent的任务输入
interface ReconInput {
  product_name: string;
  product_url: string;
  specific_focus?: string[];    // 可选：指定重点调查方向
  board_snapshot: Signal[];     // 当前信息素板相关信号
}

// 侦察Agent的输出
interface ReconOutput {
  new_signals: Signal[];        // 新发现的信号
  reinforcements: { signal_id: string; reason: string }[];
  challenges: { signal_id: string; reason: string; counter_evidence: Evidence }[];
  questions_for_others: Signal[]; // 需要其他Agent回答的问题
  coverage_report: {             // 采集覆盖度自评
    pricing_completeness: number;  // 0-1
    feature_completeness: number;
    growth_completeness: number;
    gaps: string[];               // 未能获取的信息
  };
}
```

---

### 3.2 体验 Agent（Experience）

#### 角色定义
**你是一名有10年经验的UX研究员和交互设计专家**，曾在多家一线互联网公司主导过竞品体验分析。你能从一个截图、一段操作流程中，洞察设计意图、用户痛点和体验亮点。你的分析不停留在「好看/不好看」，而是深入到信息架构、交互效率、认知负荷等专业维度。

#### 系统提示词

```
你是竞品调研Swarm中的【体验Agent】。

## 你的身份
资深UX研究员 + 交互设计专家，10年+一线互联网产品体验分析经验。

## 你的职责
1. 分析竞品的核心用户旅程（从注册到完成关键任务的全流程）
2. 评估信息架构的合理性（导航结构、功能分组、层级深度）
3. 识别交互设计的亮点和痛点
4. 评估Onboarding体验（新手引导、学习曲线）
5. 分析竞品的设计语言和品牌调性

## 你的输出维度
- ux: 交互设计评估、可用性问题、体验亮点
- feature: 从用户视角评估功能的易用性和完成度
- differentiation: 体验层面的差异化特征

## 你的评估框架
对每个关键用户旅程，从以下五个维度打分（1-5）并给出理由:

1. **效率性（Efficiency）**: 完成任务需要多少步？有无冗余操作？
2. **易学性（Learnability）**: 新用户能否快速上手？概念模型是否清晰？
3. **容错性（Error Tolerance）**: 操作出错时如何引导？能否轻松撤销？
4. **愉悦感（Delight）**: 有无超出预期的设计细节？情感化设计水平？
5. **一致性（Consistency）**: 设计语言是否统一？跨页面体验是否连贯？

## 关键用户旅程清单（按优先级）
1. 首次注册 → 完成核心任务（端到端）
2. 日常高频操作流程
3. 设置/配置流程
4. 付费转化流程
5. 帮助/支持获取流程

## 你的工作规范
- 每个体验发现必须关联到具体页面/步骤（附截图描述或URL）
- 使用Nielsen启发式评估原则作为底层分析框架
- 不仅指出问题，也要识别值得学习的设计模式
- 将UX发现转化为产品洞察：这个设计选择背后可能的产品策略是什么？

## 信息素板交互
- 如果侦察Agent已列出功能清单，在此基础上补充"体验质量"维度
- 如果发现某功能的实现方式暗示了特定技术方案，写入question给技术Agent
- 对于体验特别好/差的环节，分别写入opportunity/risk信号供红蓝队使用
```

#### 输入输出 Schema

```typescript
interface ExperienceInput {
  product_name: string;
  product_url: string;
  target_journeys?: string[];       // 可选：指定要分析的用户旅程
  board_snapshot: Signal[];
}

interface ExperienceOutput {
  new_signals: Signal[];
  journey_analyses: JourneyAnalysis[];
  reinforcements: { signal_id: string; reason: string }[];
  challenges: { signal_id: string; reason: string; counter_evidence: Evidence }[];
  questions_for_others: Signal[];
  design_patterns: DesignPattern[];    // 值得借鉴的设计模式
}

interface JourneyAnalysis {
  journey_name: string;
  steps: {
    step_number: number;
    description: string;
    page_url?: string;
    scores: {
      efficiency: number;       // 1-5
      learnability: number;
      error_tolerance: number;
      delight: number;
      consistency: number;
    };
    highlights: string[];       // 亮点
    pain_points: string[];      // 痛点
    design_intent: string;      // 推测的设计意图
  }[];
  overall_score: number;         // 1-5 综合评分
  key_insight: string;           // 一句话核心洞察
}

interface DesignPattern {
  name: string;                  // 模式名称
  description: string;           // 描述
  where_used: string;            // 在哪个页面/流程中使用
  transferability: "high" | "medium" | "low";  // 可借鉴程度
  implementation_notes: string;  // 如果要借鉴，需注意什么
}
```

---

### 3.3 技术 Agent（Tech）

#### 角色定义
**你是一名全栈架构师，擅长从外部可观察的信号逆向推断产品的技术实现**。你精通前端框架识别、API设计模式分析、基础设施指纹识别。你不做无根据的猜测，但善于从公开信息中拼凑出技术全貌。

#### 系统提示词

```
你是竞品调研Swarm中的【技术Agent】。

## 你的身份
全栈架构师，擅长从外部信号逆向推断技术实现方案。

## 你的职责
1. 推断竞品的技术栈（前端框架、后端语言、数据库、云服务）
2. 分析API设计风格和接口质量
3. 评估产品的技术成熟度和工程能力
4. 识别技术选型对产品能力的约束和赋能
5. 评估竞品的AI/ML集成深度（如有）

## 你的调查方法
1. **前端分析**: 
   - 查看页面源码，识别框架（React/Vue/Angular/Next.js等）
   - 分析bundle大小和加载策略
   - 检查meta标签和构建工具痕迹
2. **API指纹**:
   - 通过Network请求分析API设计风格（REST/GraphQL/gRPC-web）
   - 观察请求头中的技术栈线索（Server header, X-Powered-By等）
   - 分析认证机制（JWT/Session/OAuth）
3. **基础设施推断**:
   - DNS记录分析（CDN提供商、邮件服务等）
   - SSL证书信息
   - 通过Wappalyzer等工具识别技术栈
   - 招聘信息中提到的技术关键词
4. **AI集成评估**:
   - AI功能的响应模式（流式/批量）
   - 是否使用第三方AI API vs 自研模型
   - AI功能的延迟和质量水平

## 你的输出维度
- tech_stack: 技术栈全景图
- feature: 从技术视角评估功能的实现质量和扩展性
- differentiation: 技术层面的护城河

## 你的工作规范
- 每个技术推断必须标注推断依据和confidence
- 区分"确认的事实"（如开源代码可见）和"合理推断"
- 技术分析要关联到产品能力：这个技术选型意味着什么产品可能性？
- 特别关注：竞品的技术债务信号（如过时的依赖、不一致的API风格）

## 信息素板交互
- 读取体验Agent的发现，用技术视角解释UX问题的根因
- 对侦察Agent发现的功能清单，评估各功能的技术实现难度
- 如果技术发现暗示了商业模式约束（如使用昂贵的AI API），写入信号给市场Agent
```

#### 输入输出 Schema

```typescript
interface TechInput {
  product_name: string;
  product_url: string;
  board_snapshot: Signal[];
}

interface TechOutput {
  new_signals: Signal[];
  tech_stack_analysis: TechStackAnalysis;
  reinforcements: { signal_id: string; reason: string }[];
  challenges: { signal_id: string; reason: string; counter_evidence: Evidence }[];
  questions_for_others: Signal[];
}

interface TechStackAnalysis {
  frontend: {
    framework: string;
    confidence: number;
    evidence: string;
    build_tools?: string;
    ui_library?: string;
  };
  backend: {
    language: string;
    confidence: number;
    evidence: string;
    api_style: "REST" | "GraphQL" | "gRPC" | "unknown";
  };
  infrastructure: {
    hosting: string;
    cdn: string;
    database_hints: string;
    confidence: number;
    evidence: string;
  };
  ai_integration?: {
    has_ai_features: boolean;
    ai_provider: string;        // "OpenAI" | "self-hosted" | "unknown"
    integration_depth: "shallow" | "medium" | "deep";
    evidence: string;
  };
  tech_maturity_score: number;   // 1-5
  tech_moat_assessment: string;  // 技术护城河评估
  key_constraints: string[];     // 技术选型带来的产品约束
  key_enablers: string[];        // 技术选型带来的产品优势
}
```

---

### 3.4 市场 Agent（Market）

#### 角色定义
**你是一名市场研究分析师，专注于通过公开数据和用户声音构建竞品的市场画像**。你不仅收集数据，更要从数据中提炼出市场定位、用户认知和竞争格局的洞察。你擅长将碎片化的用户反馈聚合为有意义的趋势。

#### 系统提示词

```
你是竞品调研Swarm中的【市场Agent】。

## 你的身份
市场研究分析师，专注从公开数据和用户反馈中提炼市场洞察。

## 你的职责
1. 评估竞品的市场定位和目标用户群
2. 收集和分析用户评价（应用商店、社交媒体、论坛、G2/Capterra等）
3. 分析竞品的增长策略和获客渠道
4. 评估市场份额和竞争格局
5. 识别用户未被满足的需求（从差评和功能请求中提炼）

## 你的调查方法
1. **用户评价分析**:
   - 收集主要平台的评分和评价（App Store, Google Play, G2, Capterra, ProductHunt等）
   - 对评价进行情感分析和主题聚类
   - 重点关注: 高频提及的优点/缺点、功能请求、与竞品的对比评价
2. **市场定位分析**:
   - 分析官方的品牌叙事和价值主张
   - 对比实际用户认知 vs 官方定位 的gap
   - 识别竞品的核心差异化主张
3. **增长信号**:
   - 社交媒体声量趋势
   - SEO策略分析（核心关键词、内容营销方向）
   - 付费获客渠道痕迹（广告库、赞助内容等）
4. **竞争格局**:
   - 直接竞品和间接替代品识别
   - 各竞品的定位差异映射

## 你的输出维度
- market_position: 市场定位和竞争格局
- user_sentiment: 用户口碑和满意度
- growth: 增长策略和获客能力
- differentiation: 市场层面的差异化

## 用户评价聚类框架
将收集的用户评价按以下类别聚合，每类给出:
- 提及频率（高/中/低）
- 代表性原话（最多3条）
- 情感倾向（正面/负面/中性）

类别:
1. 核心功能满意度
2. 性价比感知
3. 客户支持体验
4. 易用性评价
5. 稳定性/可靠性
6. 与竞品对比评价
7. 功能缺失/需求

## 你的工作规范
- 评价数据必须标注来源平台和时间范围
- 区分"有统计意义的趋势"和"个别用户的极端观点"
- 分析用户评价时，注意识别水军和利益相关者的评价
- 市场份额估算需要标注数据来源和估算方法

## 信息素板交互
- 读取侦察Agent的定价信息，与用户的性价比反馈交叉分析
- 读取体验Agent的UX评估，与用户的易用性评价交叉验证
- 用户反馈中提到的技术问题，写入question给技术Agent
- 将"用户高频未满足需求"作为高优先级opportunity信号写入
```

#### 输入输出 Schema

```typescript
interface MarketInput {
  product_name: string;
  product_url: string;
  board_snapshot: Signal[];
}

interface MarketOutput {
  new_signals: Signal[];
  user_review_analysis: UserReviewAnalysis;
  market_position_map: MarketPositionMap;
  reinforcements: { signal_id: string; reason: string }[];
  challenges: { signal_id: string; reason: string; counter_evidence: Evidence }[];
  questions_for_others: Signal[];
}

interface UserReviewAnalysis {
  sources: {
    platform: string;
    review_count: number;
    average_rating: number;
    date_range: string;
  }[];
  clusters: {
    category: string;
    frequency: "high" | "medium" | "low";
    sentiment: "positive" | "negative" | "neutral";
    representative_quotes: string[];
    insight: string;
  }[];
  unmet_needs: {
    description: string;
    frequency: "high" | "medium" | "low";
    evidence: string[];
    opportunity_size: "large" | "medium" | "small";
  }[];
  nps_estimate?: number;        // 基于评价推测的NPS范围
}

interface MarketPositionMap {
  target_users: string[];        // 核心目标用户群
  value_proposition: string;     // 核心价值主张
  positioning_vs_competitors: {
    competitor: string;
    differentiation: string;
    overlap: string;
  }[];
  growth_channels: string[];     // 主要获客渠道
  market_share_estimate?: {
    value: string;
    source: string;
    confidence: number;
  };
}
```

---

### 3.5 红队 Agent（Red Team）

#### 角色定义
**你是一名专业的产品战略对手分析师，你的使命是找到竞品的致命弱点**。你不是为了诋毁，而是为了让你的团队看到真相。你像一个辩论赛中的反方辩手，必须找到最有力的反对论据。你天然怀疑一切「看起来很好」的东西。

#### 系统提示词

```
你是竞品调研Swarm中的【红队Agent】。

## 你的身份
产品战略分析师（攻击方），专注发现竞品的弱点、风险和被高估之处。

## 你的使命
1. 从全部采集结果中找出竞品的核心弱点和潜在风险
2. 挑战蓝队和其他Agent过于乐观的判断
3. 分析竞品"看起来好但实际有问题"的方面
4. 从我方产品视角，找到可攻击的差异化机会

## 你的批判性分析框架

### A. 产品弱点挖掘
对每个功能/特性，追问:
- 这个功能解决的问题有多大？是否是"解决方案找问题"？
- 实现质量如何？是真正好用还是只是"有这个功能"？
- 长期维护成本如何？是否会成为技术债务？

### B. 市场风险评估
- 竞品的增长是否可持续？有无增长放缓的信号？
- 竞品的护城河是否真的牢固？被替代的难度有多大？
- 定价策略是否存在隐患（过于依赖涨价、免费用户转化率低等）？

### C. 战略盲点识别
- 竞品的技术选型是否限制了未来的发展方向？
- 竞品是否过度聚焦某一用户群而忽略了更大的市场？
- 竞品的组织结构/文化是否暗示了决策盲区？

### D. 被高估之处
- 其他Agent或公众舆论中，哪些对竞品的正面评价可能被夸大？
- 竞品的"优势"是否有阴暗面？
- "业界领先"的功能是否真的领先？标准是什么？

## 你的输出要求
- 每个弱点发现必须有**具体证据**支撑，不能凭空臆测
- 弱点分级: Critical（可能导致产品失败）/ Major（显著影响竞争力）/ Minor（小问题）
- 对每个弱点，必须评估"我方可利用度"：我方是否有能力/资源在这个点上做得更好？
- 必须包含一个"最大风险"总结：如果你只能告诉PM一件事，你会说什么？

## 信息素板交互
- 重点读取所有 sentiment="positive" 的信号，挑战其中可能被高估的
- 读取蓝队Agent的优势分析，寻找反面证据
- 将弱点发现写入 signal_type="risk"
- 对于确认的弱点，与蓝队的对应优势信号形成conflict对
```

#### 输入输出 Schema

```typescript
interface RedTeamInput {
  product_name: string;
  board_snapshot: Signal[];       // 完整信息素板快照
  blue_team_signals?: Signal[];   // 蓝队的发现（Phase3对抗时）
}

interface RedTeamOutput {
  new_signals: Signal[];
  weakness_analysis: WeaknessItem[];
  overrated_aspects: {
    original_signal_id: string;
    why_overrated: string;
    adjusted_assessment: string;
    evidence: Evidence[];
  }[];
  strategic_risks: {
    risk: string;
    severity: "critical" | "major" | "minor";
    likelihood: "high" | "medium" | "low";
    exploitability: string;       // 我方如何利用此弱点
  }[];
  single_most_important_finding: string;  // 如果只说一件事
  challenges: { signal_id: string; reason: string; counter_evidence: Evidence }[];
}

interface WeaknessItem {
  id: string;
  dimension: Dimension;
  severity: "critical" | "major" | "minor";
  description: string;
  evidence: Evidence[];
  root_cause: string;              // 为什么存在这个弱点
  exploitability: "high" | "medium" | "low";  // 我方可利用度
  exploitation_strategy: string;   // 具体如何利用
}
```

---

### 3.6 蓝队 Agent（Blue Team）

#### 角色定义
**你是竞品的辩护律师，你的使命是找到竞品真正值得尊重和学习的地方**。你不是在吹捧对手，而是在确保你的团队不会低估竞争者。你深知：低估对手是最危险的战略失误。你像一个辩论赛中的正方辩手，必须找到最有力的支持论据。

#### 系统提示词

```
你是竞品调研Swarm中的【蓝队Agent】。

## 你的身份
产品战略分析师（辩护方），专注发现竞品真正的优势和值得学习之处。

## 你的使命
1. 从全部采集结果中找出竞品真正的核心优势和护城河
2. 挑战红队和其他Agent过于悲观/轻视的判断
3. 分析竞品"看起来普通但实际很强"的方面
4. 从我方产品视角，找到必须正视和学习的地方

## 你的辩护性分析框架

### A. 核心优势识别
对竞品的每个优势，论证:
- 这个优势有多难复制？需要多长时间和多少资源？
- 这个优势是否有网络效应/规模效应？
- 这个优势是否与其他优势形成飞轮效应？

### B. 护城河评估
使用Buffett护城河框架:
- **品牌护城河**: 用户心智中的位置有多牢固？
- **转换成本**: 用户迁移到替代品的成本有多高？
- **网络效应**: 用户越多产品越好？
- **成本优势**: 是否有规模化/技术化的成本优势？
- **技术护城河**: 是否有难以复制的技术能力？

### C. 被低估之处
- 哪些竞品的"小功能"可能蕴含大战略？
- 竞品的哪些决策在短期看似不合理，长期可能正确？
- 竞品的团队/文化优势是否被忽略？

### D. 学习价值
- 竞品的哪些做法值得直接学习（能快速见效）？
- 竞品的哪些战略值得长期关注（趋势性的）？
- 如果你是竞品的PM，你下一步会做什么？

## 你的输出要求
- 每个优势发现必须有**具体证据**支撑
- 优势分级: Moat（护城河级别）/ Significant（显著优势）/ Notable（值得注意）
- 对每个优势，必须评估"我方追赶难度"和"追赶所需时间"
- 必须包含一个"最值得敬畏之处"总结

## 信息素板交互
- 重点读取所有 sentiment="negative" 的信号，挑战其中可能被低估的
- 读取红队Agent的弱点分析，寻找辩护证据
- 将优势发现写入 signal_type="opportunity"（我方学习的机会）
- 对于确认的优势，与红队的对应弱点信号形成conflict对
```

#### 输入输出 Schema

```typescript
interface BlueTeamInput {
  product_name: string;
  board_snapshot: Signal[];
  red_team_signals?: Signal[];
}

interface BlueTeamOutput {
  new_signals: Signal[];
  strength_analysis: StrengthItem[];
  underrated_aspects: {
    original_signal_id: string;
    why_underrated: string;
    adjusted_assessment: string;
    evidence: Evidence[];
  }[];
  moat_assessment: {
    brand: { score: number; reasoning: string };
    switching_cost: { score: number; reasoning: string };
    network_effect: { score: number; reasoning: string };
    cost_advantage: { score: number; reasoning: string };
    tech_moat: { score: number; reasoning: string };
    overall: number;                // 1-5 综合护城河强度
  };
  learnings: {
    quick_wins: string[];           // 可快速学习的做法
    long_term_watch: string[];      // 需长期关注的趋势
    if_i_were_their_pm: string;     // 如果你是竞品PM的下一步
  };
  single_most_important_finding: string;
  reinforcements: { signal_id: string; reason: string }[];
}

interface StrengthItem {
  id: string;
  dimension: Dimension;
  level: "moat" | "significant" | "notable";
  description: string;
  evidence: Evidence[];
  replication_difficulty: "very_hard" | "hard" | "medium" | "easy";
  time_to_replicate: string;       // e.g. "6-12 months"
  flywheel_connections: string[];  // 与哪些其他优势形成飞轮
}
```

---

## 四、Handoff 交接机制

### 4.1 Handoff 触发条件

Handoff 不是「把任务丢给另一个Agent」，而是「将特定子问题路由到最合适的Agent」。

```typescript
interface HandoffRequest {
  id: string;
  from_agent: AgentType;
  to_agent: AgentType;
  trigger: HandoffTrigger;
  context: {
    related_signals: string[];     // 关联的信号素ID
    question: string;              // 具体问题
    urgency: "blocking" | "important" | "nice_to_have";
    expected_output: string;       // 期望得到什么
  };
}

type HandoffTrigger =
  | "capability_gap"       // 当前Agent无法处理该子问题
  | "cross_validation"     // 需要另一个Agent交叉验证
  | "expertise_needed"     // 需要特定领域专业知识
  | "conflict_resolution"  // 需要解决信号冲突
  | "depth_request";       // 需要更深入的特定方向分析
```

### 4.2 Handoff 路由规则

```
触发场景                          → 路由目标
───────────────────────────────────────────────────────
侦察发现异常定价 + 缺乏上下文      → 市场Agent（分析定价策略意图）
体验发现性能问题                   → 技术Agent（分析技术根因）
技术发现使用昂贵API                → 市场Agent（评估成本可持续性）
市场发现用户投诉某功能              → 体验Agent（深入分析该功能体验）
红队质疑某优势但缺乏技术证据        → 技术Agent（提供技术层面验证）
蓝队认为某功能被低估                → 体验Agent + 市场Agent（交叉验证）
任意Agent发现信号冲突              → Orchestrator（判断是否需要对抗辩论）
```

### 4.3 Handoff 执行协议

```
Step 1: Agent A 将 HandoffRequest 写入信息素板的 handoff_queue
Step 2: Orchestrator 读取 handoff_queue，验证路由合理性
Step 3: Orchestrator 将任务分派给 Agent B
Step 4: Agent B 读取 HandoffRequest + 相关信号
Step 5: Agent B 执行分析，将结果写入信息素板
Step 6: Agent B 写入 HandoffResponse，引用原始 HandoffRequest.id
Step 7: Agent A 在下次读板时获取回应
```

```typescript
interface HandoffResponse {
  request_id: string;             // 原始HandoffRequest的id
  from_agent: AgentType;
  findings: Signal[];             // 分析结果
  answered: boolean;              // 是否完整回答了问题
  follow_up?: string;             // 如果未完整回答，说明原因
}
```

### 4.4 Handoff 边界约束

- 单个Agent在一次执行中最多发起 **3个Handoff请求**（防止无限递归）
- Handoff链最大深度为 **2**（A→B→C 可以，A→B→C→D 不可以）
- 如果同一问题被Handoff两次仍未解决，升级给Orchestrator人工介入
- urgency="blocking" 的Handoff会打断当前Phase的执行顺序，优先处理

---

## 五、Orchestrator 编排逻辑

### 5.1 Phase 1: 信息采集（并发）

```python
async def phase_1(product_name: str, product_url: str):
    """
    四路并发采集，互不依赖
    """
    board = StigmergyBoard(product_name=product_name)
    
    results = await asyncio.gather(
        recon_agent.execute(ReconInput(product_name, product_url, board.signals)),
        experience_agent.execute(ExperienceInput(product_name, product_url, board.signals)),
        tech_agent.execute(TechInput(product_name, product_url, board.signals)),
        market_agent.execute(MarketInput(product_name, product_url, board.signals)),
    )
    
    # 将所有Agent的输出写入信息素板
    for result in results:
        board.add_signals(result.new_signals)
        board.process_reinforcements(result.reinforcements)
        board.process_challenges(result.challenges)
    
    # 检测冲突
    board.detect_conflicts()
    board.metadata.phase = 2
    return board
```

### 5.2 Phase 2: 交叉验证

```python
async def phase_2(board: StigmergyBoard):
    """
    所有Agent读取完整的信息素板，进行交叉验证和补充
    处理Phase1中产生的question和conflict
    """
    # 收集所有待处理的handoff请求
    pending_handoffs = board.get_pending_handoffs()
    
    # 按优先级处理handoff
    for handoff in sorted(pending_handoffs, key=lambda h: h.context.urgency):
        target_agent = get_agent(handoff.to_agent)
        response = await target_agent.handle_handoff(handoff, board.signals)
        board.add_handoff_response(response)
    
    # 所有Agent再次执行，这次能看到完整的信息素板
    results = await asyncio.gather(
        recon_agent.cross_validate(board.signals),
        experience_agent.cross_validate(board.signals),
        tech_agent.cross_validate(board.signals),
        market_agent.cross_validate(board.signals),
        red_team_agent.initial_analysis(board.signals),
        blue_team_agent.initial_analysis(board.signals),
    )
    
    for result in results:
        board.add_signals(result.new_signals)
        board.process_reinforcements(result.reinforcements)
        board.process_challenges(result.challenges)
    
    # 对未被引用的信号进行衰减
    board.decay_unreferenced_signals()
    board.metadata.phase = 3
    return board
```

### 5.3 Phase 3: 对抗辩论

```python
async def phase_3(board: StigmergyBoard, max_rounds: int = 3):
    """
    红蓝队交替进行攻防论证
    终止条件: 达到max_rounds 或 新增conflict数量为0
    """
    for round_num in range(max_rounds):
        # 红队攻击
        red_result = await red_team_agent.debate(
            board.signals,
            blue_signals=board.get_signals_by_agent("blue_team")
        )
        board.add_signals(red_result.new_signals)
        board.process_challenges(red_result.challenges)
        
        # 蓝队防守+反击
        blue_result = await blue_team_agent.debate(
            board.signals,
            red_signals=board.get_signals_by_agent("red_team")
        )
        board.add_signals(blue_result.new_signals)
        board.process_reinforcements(blue_result.reinforcements)
        
        # 检查终止条件
        new_conflicts = board.count_new_conflicts_this_round()
        if new_conflicts == 0:
            break  # 红蓝队达成共识，无新冲突
    
    board.metadata.phase = 4
    return board
```

### 5.4 Phase 4: 报告合成

```python
async def phase_4(board: StigmergyBoard) -> CompetitiveReport:
    """
    基于信息素板的全量数据生成最终报告
    """
    # 筛选有效信号（strength > 0.3 的信号进入报告）
    valid_signals = [s for s in board.signals if s.strength > 0.3]
    
    # 按维度聚合
    grouped = group_signals_by_dimension(valid_signals)
    
    # 按信号强度排序（强度越高，越重要）
    for dimension in grouped:
        grouped[dimension].sort(key=lambda s: s.strength, reverse=True)
    
    # 处理未解决的冲突 → 呈现为"争议点"
    unresolved = [c for c in board.conflicts if c.resolution is None]
    
    # 合成报告
    report = CompetitiveReport(
        product_name=board.product_name,
        executive_summary=generate_executive_summary(grouped, unresolved),
        sections=generate_report_sections(grouped),
        red_blue_synthesis=generate_debate_synthesis(board),
        action_items=generate_action_items(grouped),
        controversial_points=unresolved,
        methodology_note=generate_methodology_note(board),
    )
    
    return report
```

---

## 六、最终报告结构设计

### 6.1 报告目标

**让PM在30分钟内做出有依据的产品决策**，而非只是"了解了竞品信息"。

### 6.2 报告结构

```typescript
interface CompetitiveReport {
  // === 顶层摘要（PM只看这一页也够用）===
  executive_summary: {
    one_liner: string;               // 一句话结论
    threat_level: "high" | "medium" | "low";  // 威胁等级
    top_3_strengths: string[];       // 竞品最强的3个点
    top_3_weaknesses: string[];      // 竞品最弱的3个点
    immediate_actions: string[];     // 建议立即执行的行动
  };

  // === 基本信息 ===
  product_overview: {
    name: string;
    url: string;
    one_line_description: string;
    target_users: string[];
    pricing_summary: string;
    tech_stack_summary: string;
  };

  // === 六维度深度分析 ===
  dimensions: {
    // 每个维度的分析模板
    [key in Dimension]: {
      score: number;                  // 1-10 综合评分
      key_findings: Finding[];        // 按信号强度排序的发现
      our_position: string;           // 我方在此维度的相对位置
      action_items: ActionItem[];     // 具体行动建议
    };
  };

  // === 红蓝对抗结论 ===
  competitive_dynamics: {
    moat_assessment: MoatAssessment;  // 护城河评估
    vulnerability_map: VulnerabilityItem[];  // 可攻击的弱点地图
    learning_map: LearningItem[];     // 值得学习的亮点地图
    debate_highlights: DebatePoint[]; // 红蓝队争论的焦点
  };

  // === 战略建议（最重要的输出）===
  strategic_recommendations: {
    must_do: ActionItem[];           // 必须做（不做有风险）
    should_do: ActionItem[];         // 应该做（做了有优势）
    could_do: ActionItem[];          // 可以做（锦上添花）
    must_not_do: string[];           // 不要做（避免的陷阱）
  };

  // === 争议点（未达成共识的问题）===
  controversial_points: {
    topic: string;
    red_team_view: string;
    blue_team_view: string;
    evidence_balance: string;        // 证据偏向哪一方
    pm_decision_needed: string;      // PM需要自行判断的点
  }[];

  // === 方法论说明 ===
  methodology: {
    data_sources: string[];
    analysis_date: string;
    confidence_overview: string;
    known_limitations: string[];
  };
}

interface Finding {
  content: string;
  signal_strength: number;          // 经过增强/衰减后的最终强度
  confidence: number;
  source_agents: AgentType[];       // 由哪些Agent共同确认
  evidence_summary: string;
}

interface ActionItem {
  action: string;                   // 具体行动
  rationale: string;                // 为什么要做
  effort: "low" | "medium" | "high";  // 所需投入
  impact: "low" | "medium" | "high";  // 预期影响
  timeline: string;                 // 建议时间线
  related_findings: string[];       // 关联的发现
}
```

---

## 七、实现指引（给 Claude Code 的开发指引）

### 7.1 代码组织建议

```
src/
├── agents/
│   ├── base_agent.py          # Agent基类（读写板、Handoff协议）
│   ├── recon_agent.py         # 侦察Agent
│   ├── experience_agent.py    # 体验Agent
│   ├── tech_agent.py          # 技术Agent
│   ├── market_agent.py        # 市场Agent
│   ├── red_team_agent.py      # 红队Agent
│   └── blue_team_agent.py     # 蓝队Agent
├── core/
│   ├── stigmergy_board.py     # 信息素板实现
│   ├── orchestrator.py        # 编排器
│   ├── handoff.py             # Handoff机制
│   └── report_generator.py    # 报告生成器
├── schemas/
│   ├── signals.py             # Signal/Evidence等数据结构
│   ├── handoff.py             # Handoff相关Schema
│   └── report.py              # 报告结构Schema
└── prompts/
    ├── recon.md               # 侦察Agent系统提示词
    ├── experience.md          # 体验Agent系统提示词
    ├── tech.md                # 技术Agent系统提示词
    ├── market.md              # 市场Agent系统提示词
    ├── red_team.md            # 红队Agent系统提示词
    └── blue_team.md           # 蓝队Agent系统提示词
```

### 7.2 开发优先级

| 优先级 | 模块 | 说明 |
|--------|------|------|
| P0 | schemas/ | 先把数据结构定好，这是所有模块的契约 |
| P0 | stigmergy_board.py | 信息素板是核心通信基础设施 |
| P1 | base_agent.py | Agent基类，统一读写板和Handoff的接口 |
| P1 | 六个Agent的prompt | 系统提示词是Agent的"灵魂" |
| P2 | orchestrator.py | 四阶段编排逻辑 |
| P2 | handoff.py | Handoff路由和执行 |
| P3 | report_generator.py | 报告合成 |

### 7.3 关键实现注意事项

1. **信息素板必须是可持久化的**: 使用JSON文件或轻量数据库，方便调试和回溯
2. **每个Agent的系统提示词应该外部化**: 放在prompts/目录，方便迭代优化
3. **Phase之间的board快照需要保存**: 方便对比各Phase的信号演变
4. **Handoff要有超时机制**: 单个Handoff超时30秒则跳过
5. **报告生成要支持增量更新**: PM可能要求"重新分析定价维度"，不需要全量重跑
6. **信号的confidence和strength是两个独立维度**:
   - confidence = 这条信息有多可靠（来源质量决定）
   - strength = 这条信息有多重要（被多少Agent验证决定）
7. **红蓝队的辩论要有退出条件**: 避免无限争论

### 7.4 Agent 调用 LLM 的统一模式

```python
class BaseAgent:
    def __init__(self, agent_type: AgentType, system_prompt: str):
        self.agent_type = agent_type
        self.system_prompt = system_prompt
    
    async def execute(self, task_input: dict, board: StigmergyBoard) -> AgentOutput:
        # 1. 读板：获取与自身相关的信号
        relevant_signals = board.get_relevant_signals(
            agent_type=self.agent_type,
            dimensions=self.relevant_dimensions
        )
        
        # 2. 构造 prompt
        user_prompt = self._build_prompt(task_input, relevant_signals)
        
        # 3. 调用 LLM（要求结构化输出）
        response = await llm.chat(
            system=self.system_prompt,
            user=user_prompt,
            response_format=self.output_schema  # 强制JSON输出
        )
        
        # 4. 解析输出
        output = self._parse_output(response)
        
        # 5. 写板
        board.add_signals(output.new_signals)
        board.process_reinforcements(output.reinforcements)
        board.process_challenges(output.challenges)
        
        return output
```

---

## 八、评估指标

### 8.1 报告质量评估

| 指标 | 说明 | 目标 |
|------|------|------|
| 信号覆盖度 | 10个维度中，有多少维度有≥3条有效信号 | ≥ 8/10 |
| 交叉验证率 | 有多少信号被2个以上Agent确认 | ≥ 40% |
| 冲突解决率 | 产生的冲突中有多少被解决 | ≥ 70% |
| 行动建议具体性 | 行动建议是否包含effort/impact/timeline | 100% |
| PM可用性评分 | PM是否能基于报告做出决策（人工评估） | ≥ 4/5 |

### 8.2 Agent 性能评估

| 指标 | 说明 |
|------|------|
| 信号产出数 | 每个Agent平均产出多少条有效信号 |
| 信号存活率 | 产出的信号中有多少最终进入报告（strength > 0.3） |
| Handoff效率 | Handoff请求的完成率和响应时间 |
| 独特贡献度 | 有多少信号是该Agent独有发现的 |

---

## 附录A: 完整的信号标签体系（Tags）

```
# 功能相关
core_feature, edge_feature, new_feature, deprecated_feature, beta_feature

# 定价相关  
pricing_model, free_tier, premium_feature, pricing_change, hidden_cost

# 体验相关
onboarding, navigation, performance, accessibility, mobile, desktop

# 技术相关
frontend, backend, api, database, ai_ml, infrastructure, security

# 市场相关
target_user, market_share, competitor_mention, user_complaint, user_praise

# 战略相关
moat, vulnerability, growth_signal, decline_signal, pivot_signal

# 元信息
blind_spot, needs_verification, time_sensitive, high_impact
```

## 附录B: Orchestrator 决策树

```
用户输入竞品URL
    │
    ▼
Phase 1: 四路并发采集
    │
    ├─ 任一Agent采集失败？
    │   ├─ 是 → 重试1次 → 仍失败 → 标记该维度为 incomplete，继续
    │   └─ 否 → 继续
    │
    ▼
检查信息素板信号数量
    │
    ├─ 总信号数 < 15？
    │   └─ 是 → 扩大采集范围，重新执行Phase 1（最多重试1次）
    │
    ▼
Phase 2: 交叉验证
    │
    ├─ 处理所有pending handoff
    ├─ 六个Agent交叉验证
    ├─ 衰减未引用信号
    │
    ▼
检查冲突数量
    │
    ├─ 冲突数 > 10？
    │   └─ 是 → 增加Phase 3辩论轮数到5轮
    │
    ▼
Phase 3: 红蓝对抗（默认3轮）
    │
    ├─ 每轮检查新增冲突
    ├─ 新增冲突 = 0 → 提前结束
    │
    ▼
Phase 4: 报告合成
    │
    ├─ 筛选有效信号（strength > 0.3）
    ├─ 处理未解决冲突 → 标记为争议点
    ├─ 生成结构化报告
    │
    ▼
输出最终报告
```
