# guangsu-coach-skill

光速英语记单词与语法教练：一个可用于支持 Skill 的教学规则包，整理《光速单词》中的“双语论”和“连锁法”，用于互动记单词、课程化过词表、语法讲解、长难句拆解、复习测验和考前冲刺。

## 功能

- **互动记单词**：根据词形、读音和语义建立可解释词链，并配小测验收。
- **课程模式**：按阶段推进 0→2000→4000→6000→12000 词，前三阶段使用本地确定性词表。
- **语法与长难句**：提供语法框架和五步拆解方法。
- **测验复习**：基于学习进度生成客观题并记录错词。
- **考前冲刺**：优先过高频核心链。
- **本地词表工具**：校验词表、课程阶段数据和 PDF 派生词头。

## 目录结构

```text
SKILL.md                         # Skill 主规则与模式路由
references/                      # 双语论、连锁法、现成词链、语法资料
assets/wordlists/                # 高考 3500 / CET4 / 考研 5500 / 大纲 6000 词表
assets/pdf-derived/              # 本地 PDF 派生词头索引与来源说明
tools/validate_wordlists.py      # 词表与课程阶段校验
tools/import_local_pdfs.py       # 从本地 PDF 目录重建词头索引
```

## 使用

将该目录作为 Skill 安装到支持 Agent Skills 的环境中后，直接向 Agent 提出：

- “帮我记单词：noon, moon, soon”
- “开始学高考 3500 词”
- “什么是定语从句？”
- “拆解这个长难句”
- “考考我 / 复习 / 明天考试，快过一遍”

## 常用校验命令

修改 `assets/wordlists/` 后运行：

```powershell
python tools/validate_wordlists.py --curriculum
```

导入或更新本地 PDF 词头后按需重建索引：

```powershell
python tools/import_local_pdfs.py --help
```

## 方法边界

本仓库中的方法是记忆线索和教学呈现顺序，不是词源学或语言学结论。Skill 明确禁止编造谐音故事、字母形象故事或牵强词源解释；当联系不可靠时，应改为平实讲解词义、词性和搭配。

## 仓库

https://github.com/virtualstarsmith/guangsu-coach-skill
