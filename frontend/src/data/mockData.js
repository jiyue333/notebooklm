// Mock data for the NotebookLM clone

export const mockUser = {
    id: 'user-001',
    name: '张三',
    email: 'zhangsan@example.com',
    avatar: null,
    settings: {
        outputLanguage: '中文',
        model: 'GPT-4o',
        theme: 'light',
    },
};

export const mockNotebooks = [
    {
        id: 'nb-001',
        title: 'Smart Monitoring: Crowd Sensing, Edge Computing',
        emoji: '👥',
        color: '#5B6ABF',
        date: '2026年2月8日',
        tags: ['视觉', '论文', '边缘计算'],
        lastOpenedAt: '2026-03-25T09:30:00Z',
        sourceCount: 31,
        articles: [
            {
                id: 'art-001',
                title: 'Deep Research 报告：基于 YOLO 的人群密度估计',
                type: 'research',
                icon: '🔬',
                author: 'Deep Research',
                date: '2026年02月08日 14:30',
                selected: true,
                content: `# 基于 YOLO 的人群密度估计

## 1. 引言

人群密度估计是计算机视觉领域中一个重要且具有挑战性的研究方向。随着城市化进程的加速和大型公共活动的增多，准确估计人群密度对于公共安全管理、交通规划和商业分析等方面具有重要意义。

传统的人群计数方法主要依赖于手动标注和简单的图像处理技术，但这些方法在面对复杂场景时往往表现不佳。近年来，基于深度学习的方法，特别是YOLO（You Only Look Once）系列算法，在目标检测领域取得了显著的进展。

## 2. YOLO 算法概述

### 2.1 YOLO 的基本原理

YOLO 算法将目标检测问题转化为回归问题，通过单次前向传播即可预测目标的位置和类别。与传统的两阶段检测器（如 Faster R-CNN）相比，YOLO 具有以下优势：

- **速度快**：单次前向传播完成检测，适合实时应用
- **全局信息**：对整张图像进行推理，减少背景误检
- **泛化能力**：在不同领域展现出良好的迁移学习能力

### 2.2 YOLO 版本演进

| 版本 | 发布时间 | 主要改进 |
|------|----------|----------|
| YOLOv1 | 2016 | 开创性的单阶段检测 |
| YOLOv2 | 2017 | 引入 Batch Normalization |
| YOLOv3 | 2018 | 多尺度预测 |
| YOLOv4 | 2020 | CSPDarknet 主干网络 |
| YOLOv5 | 2020 | PyTorch 实现 |
| YOLOv8 | 2023 | Anchor-Free 检测 |
| YOLOv11 | 2024 | 增强特征融合 |

## 3. 人群密度估计方法

### 3.1 基于检测的方法

基于检测的人群密度估计方法通过检测每个个体来实现计数。这类方法在低密度场景中表现良好，但在高密度场景中可能因为遮挡而导致漏检。

### 3.2 基于密度图的方法

密度图方法通过学习从输入图像到密度图的映射来估计人群密度。常用的密度图生成方法包括：

- 高斯核函数
- 自适应核函数
- 几何自适应核函数

### 3.3 混合方法

结合检测和密度估计的混合方法近年来受到关注。这类方法在不同密度区域采用不同的策略，以提高整体估计精度。

## 4. 从检测结果到空间密度与热点的分析方法

### 4.1 空间密度分析

将检测结果转化为空间密度分布，可以帮助理解人群的聚集模式：

- **核密度估计（KDE）**：使用高斯核函数估计空间点密度
- **Voronoi 图分析**：基于最近邻关系划分空间区域
- **热力图可视化**：直观展示密度分布

### 4.2 热点分析

建议升级为：统计量的时空热点挖掘算法。

**理由**：简单的"密度图"只是视觉展示，引入 Getis-Ord Gi* 算法可以从统计学上自动识别具有显著性的"拥挤热点"和"异常冷点"，提升分析的决策价值。

## 5. 计数稳定化与误差控制机制

### 5.1 时间平滑

建议补充：引入多目标跟踪算法（如 ByteTrack 或 BoT-SORT）。

**理由**：纯检测会导致人数跳变（上一帧 100 人，下一帧 98 人）。结合跟踪算法可以平滑计数曲线，并计算驻留时长（Dwell Time），这是商业分析的重要指标。

### 5.2 空间一致性

通过空间约束确保相邻区域的密度估计保持一致性，避免出现突变。

## 6. 实现途径

### 6.1 数据工程与模型开发

建议明确使用 **NWPU-Crowd**（目前最大规模拥挤数据集，含负样本）进行预训练，以提升模型的抗干扰能力。

### 6.2 系统实现与集成部署

建议提及 **TensorRT** 或 **ONNX Runtime** 加速技术，以及在边缘设备（如 Jetson Orin 或 Raspberry Pi）上的部署验证。

## 7. 优化后的详细大纲（参考版）

这份大纲融入了最新的技术关键词，显得更加专业和前沿。

### 7.1 数据预处理
- 图像增强策略
- 标注质量控制
- 数据均衡采样

### 7.2 模型架构
- 主干网络选择
- 特征金字塔网络
- 检测头设计

### 7.3 训练策略
- 学习率调度
- 损失函数设计
- 正则化方法

## 8. 结论

基于 YOLO 的人群密度估计方法在实时性和准确性之间取得了良好的平衡。未来的研究方向包括：

1. 轻量化模型设计
2. 跨场景泛化能力提升
3. 与边缘计算的深度融合
4. 多模态信息融合（视频+音频+WiFi）`,
                toc: [
                    { id: 'sec-1', title: '1. 引言', level: 1 },
                    { id: 'sec-2', title: '2. YOLO 算法概述', level: 1 },
                    { id: 'sec-2-1', title: '2.1 YOLO 的基本原理', level: 2 },
                    { id: 'sec-2-2', title: '2.2 YOLO 版本演进', level: 2 },
                    { id: 'sec-3', title: '3. 人群密度估计方法', level: 1 },
                    { id: 'sec-3-1', title: '3.1 基于检测的方法', level: 2 },
                    { id: 'sec-3-2', title: '3.2 基于密度图的方法', level: 2 },
                    { id: 'sec-3-3', title: '3.3 混合方法', level: 2 },
                    { id: 'sec-4', title: '4. 从检测结果到空间密度与热点的分析方法', level: 1 },
                    { id: 'sec-5', title: '5. 计数稳定化与误差控制机制', level: 1 },
                    { id: 'sec-6', title: '6. 实现途径', level: 1 },
                    { id: 'sec-7', title: '7. 优化后的详细大纲', level: 1 },
                    { id: 'sec-8', title: '8. 结论', level: 1 },
                ],
            },
            {
                id: 'art-002',
                title: '52CV/CVPR-2025-Papers - GitHub',
                type: 'github',
                icon: '💻',
                author: 'GitHub',
                date: '2026年01月15日 10:20',
                selected: true,
                content: `# CVPR 2025 论文精选

## 人群计数与密度估计

### 概述

CVPR 2025 收录了多篇关于人群计数和密度估计的前沿论文。本文整理了其中最具代表性的工作。

## 重点论文

### 1. CrowdDiff: Multi-Scale Crowd Density Estimation

**作者**: Zhang et al.

**摘要**: 本文提出了一种基于扩散模型的多尺度人群密度估计方法。通过将密度图生成过程建模为去噪扩散过程，在多个公开数据集上取得了 SOTA 结果。

**主要贡献**:
- 首次将扩散模型应用于人群密度估计
- 多尺度特征融合机制
- 自适应噪声调度策略

### 2. TokenCount: Vision Transformer for Dense Crowd

**作者**: Li et al.

**摘要**: 提出了一种基于 Vision Transformer 的人群计数方法，通过 token-wise 密度回归实现精确计数。

### 3. Edge-Crowd: On-Device Crowd Analytics

**作者**: Wang et al.

**摘要**: 面向边缘设备的轻量化人群分析框架，在保持高精度的同时实现了 30+ FPS 的推理速度。

## 数据集更新

| 数据集 | 图像数 | 平均计数 | 最大计数 |
|--------|--------|----------|----------|
| ShanghaiTech A | 482 | 501 | 3,139 |
| ShanghaiTech B | 716 | 123 | 578 |
| UCF-QNRF | 1,535 | 815 | 12,865 |
| NWPU-Crowd | 5,109 | 418 | 20,033 |
| JHU-CROWD++ | 4,372 | 346 | 25,791 |`,
                toc: [
                    { id: 'sec-1', title: '概述', level: 1 },
                    { id: 'sec-2', title: '重点论文', level: 1 },
                    { id: 'sec-3', title: '数据集更新', level: 1 },
                ],
            },
            {
                id: 'art-003',
                title: 'A Crowded Object Counting System',
                type: 'paper',
                icon: '📄',
                author: 'IEEE Conference',
                date: '2025年12月20日 09:00',
                selected: true,
                content: `# A Crowded Object Counting System

## Abstract

This paper presents a comprehensive system for counting objects in crowded scenes...

## 1. Introduction

Counting objects in densely crowded scenes remains a challenging computer vision problem...`,
                toc: [
                    { id: 'sec-1', title: 'Abstract', level: 1 },
                    { id: 'sec-2', title: '1. Introduction', level: 1 },
                ],
            },
            {
                id: 'art-004',
                title: 'Benchmarking Lightweight YOLO Models',
                type: 'paper',
                icon: '📊',
                author: 'arXiv',
                date: '2025年11月08日 16:45',
                selected: true,
                content: `# Benchmarking Lightweight YOLO Models

## 概要

本文对多种轻量级 YOLO 模型进行了全面的基准测试...`,
                toc: [
                    { id: 'sec-1', title: '概要', level: 1 },
                ],
            },
            {
                id: 'art-005',
                title: 'Count2Density: Crowd Density Estimation',
                type: 'paper',
                icon: '📈',
                author: 'CVPR 2025',
                date: '2025年10月30日 11:15',
                selected: false,
                content: `# Count2Density: Crowd Density Estimation

## 研究背景

人群密度估计方法的新框架...`,
                toc: [
                    { id: 'sec-1', title: '研究背景', level: 1 },
                ],
            },
        ],
    },
    {
        id: 'nb-002',
        title: 'Untitled notebook',
        emoji: '📒',
        color: '#8B7355',
        date: '2026年2月8日',
        tags: ['待整理'],
        lastOpenedAt: '2026-03-24T16:00:00Z',
        sourceCount: 0,
        articles: [],
    },
    {
        id: 'nb-003',
        title: 'Modern Database Systems: Architecture & Practice',
        emoji: '🗄️',
        color: '#6B8E6B',
        date: '2026年1月7日',
        tags: ['数据库', '架构'],
        lastOpenedAt: '2026-03-23T12:00:00Z',
        sourceCount: 29,
        articles: [
            {
                id: 'art-010',
                title: '数据库系统架构概述',
                type: 'article',
                icon: '📚',
                selected: true,
                content: `# 数据库系统架构概述\n\n## 存储引擎\n\n现代数据库系统的存储引擎...`,
                toc: [
                    { id: 'sec-1', title: '存储引擎', level: 1 },
                ],
            },
        ],
    },
    {
        id: 'nb-004',
        title: 'LoRA: Low-Rank Adaptation of Large Language Models',
        emoji: '📉',
        color: '#7B68AE',
        date: '2026年1月6日',
        tags: ['微调', 'LLM'],
        lastOpenedAt: '2026-03-20T10:00:00Z',
        sourceCount: 3,
        articles: [],
    },
    {
        id: 'nb-005',
        title: 'YOLO Object Detection: Models, Benchmarks',
        emoji: '🔍',
        color: '#5F8F5F',
        date: '2025年12月30日',
        tags: ['检测', 'Benchmark'],
        lastOpenedAt: '2026-03-18T10:00:00Z',
        sourceCount: 8,
        articles: [],
    },
    {
        id: 'nb-006',
        title: 'AI 调研',
        emoji: '🔌',
        color: '#8B8378',
        date: '2025年12月29日',
        tags: ['AI', '调研'],
        lastOpenedAt: '2026-03-17T10:00:00Z',
        sourceCount: 32,
        articles: [],
    },
    {
        id: 'nb-007',
        title: 'CS146S',
        emoji: '💻',
        color: '#6B8E8E',
        date: '2025年12月28日',
        tags: ['课程'],
        lastOpenedAt: '2026-03-14T10:00:00Z',
        sourceCount: 1,
        articles: [],
    },
    {
        id: 'nb-008',
        title: '医学免疫学：基础理论与应用',
        emoji: '🔬',
        color: '#7B6888',
        date: '2025年12月27日',
        tags: ['医学'],
        lastOpenedAt: '2026-03-10T10:00:00Z',
        sourceCount: 4,
        articles: [],
    },
    {
        id: 'nb-009',
        title: 'LLM 规范驱动开发：理念、架构与实践',
        emoji: '🏗️',
        color: '#8B7D5F',
        date: '2025年12月16日',
        tags: ['规范驱动开发'],
        lastOpenedAt: '2026-03-05T10:00:00Z',
        sourceCount: 3,
        articles: [],
    },
];

export const mockChatMessages = [
    {
        id: 'msg-001',
        role: 'assistant',
        content: '你好！我是你的 AI 研究助手。我已经阅读了你笔记本中的所有来源资料。你可以问我任何关于这些资料的问题，我会根据来源内容来回答。',
        timestamp: '14:30',
    },
    {
        id: 'msg-002',
        role: 'user',
        content: '请总结一下 YOLO 在人群密度估计方面的主要优势',
        timestamp: '14:32',
    },
    {
        id: 'msg-003',
        role: 'assistant',
        content: `根据资料，YOLO 在人群密度估计方面有以下主要优势：

1. **速度快** - 单次前向传播即可完成检测，非常适合实时人群监控应用
2. **全局信息利用** - 对整张图像进行推理，有效减少背景误检
3. **强泛化能力** - 在不同场景间展现出良好的迁移学习能力
4. **端到端训练** - 简化了整体流程

此外，结合 ByteTrack 或 BoT-SORT 等跟踪算法，可以进一步平滑计数曲线并计算驻留时长。 [1][2]`,
        timestamp: '14:33',
    },
];

export const availableModels = [
    { id: 'gpt-4o', name: 'GPT-4o', provider: 'OpenAI' },
    { id: 'gpt-4o-mini', name: 'GPT-4o Mini', provider: 'OpenAI' },
    { id: 'claude-3.5', name: 'Claude 3.5 Sonnet', provider: 'Anthropic' },
    { id: 'gemini-2.0', name: 'Gemini 2.0 Flash', provider: 'Google' },
    { id: 'deepseek-r1', name: 'DeepSeek R1', provider: 'DeepSeek' },
];

export const outputLanguages = [
    '中文', 'English', '日本語', '한국어', 'Français', 'Deutsch', 'Español',
];

export const mockSearchResults = [
    {
        id: 'sr-001',
        title: '谷歌搜索技巧大全| 谷歌高级搜索语法指令原创 - CSDN 博客',
        description: '系统总结了常用的高级搜索指令，是快速进阶搜索高手的必备手册。',
        icon: '🔴',
        iconColor: '#E74C3C',
        url: 'https://blog.csdn.net/example1',
        selected: true,
    },
    {
        id: 'sr-002',
        title: '如何像专家一样高效使用 Google 搜索 - freeCodeCamp',
        description: '提供了专家级的搜索建议，教你如何精准地提出问题并获取答案。',
        icon: '🔵',
        iconColor: '#3498DB',
        url: 'https://freecodecamp.org/example2',
        selected: true,
    },
    {
        id: 'sr-003',
        title: '2025.10.21 获取学术期刊全文 (人文社科篇',
        description: '深度讲解了学术资源的检索策略，特别是在人文社科领域的全攻略。',
        icon: '🟠',
        iconColor: '#E67E22',
        url: 'https://example.com/academic',
        selected: true,
    },
    {
        id: 'sr-004',
        title: '研 0 必看，这 3 款神器分分钟找到你需要的强关联文献 - 丁香园',
        description: '推荐了三款关联文献发现工具，帮助你通过一篇论文挖掘整个领域。',
        icon: '💠',
        iconColor: '#9B59B6',
        url: 'https://dxy.cn/example4',
        selected: true,
    },
    {
        id: 'sr-005',
        title: '互联网档案 (Internet Archive) 使用指南：人人都能用的网络时光...',
        description: '详尽介绍了互联网档案库的使用方法，带你找回消失的网页记忆。',
        icon: '🟤',
        iconColor: '#795548',
        url: 'https://example.com/archive',
        selected: true,
    },
    {
        id: 'sr-006',
        title: '超好用的 Similarsites：一键搜索同类相似网站的神器| 涯术说',
        description: '分享了寻找同类相似网站的利器，是扩展信息源和替代资源的佳作。',
        icon: '🏠',
        iconColor: '#00BCD4',
        url: 'https://example.com/similar',
        selected: true,
    },
    {
        id: 'sr-007',
        title: '推荐三个好用的文献检索 AI 工具，大幅提高检索效率 - SCI 论文...',
        description: '介绍了 AI 赋能的文献检索工具，展示了如何利用大模型提高调研效...',
        icon: '✏️',
        iconColor: '#607D8B',
        url: 'https://example.com/ai-tools',
        selected: true,
    },
    {
        id: 'sr-008',
        title: '第 1 章 计算机信息检索基础知识',
        description: '系统介绍了信息检索的基本原理和方法。',
        icon: '🌐',
        iconColor: '#FF9800',
        url: 'https://example.com/chapter1',
        selected: true,
    },
];
