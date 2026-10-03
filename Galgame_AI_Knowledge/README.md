# 《近月少女的礼仪》AI 知识库

把 Navel《月に寄りそう乙女の作法》（近月少女的礼仪）的剧本，转换成可检索、可追溯、
可供 AI 使用的结构化资料。当前版本包含**日文原文全剧本**与两位指定角色
（桜小路ルナ、大蔵遊星／小倉朝日）的完整资料。

## 一、快速导航

| 想看什么 | 打开 |
| --- | --- |
| 两位角色的完整分析 | `knowledge/characters/sakuragi_luna.md`、`knowledge/characters/ookura_yuusei.md` |
| 全部台词（按角色） | `characters/sakuragi_luna.json`（4995 句）、`characters/ookura_yuusei.json`（8668 句） |
| 全剧本（结构化） | `cleaned/messages.jsonl`（41919 条） |
| 全剧本（含指令的原始层） | `raw/script_lines.jsonl` |
| 每个 pack 的原始导出 | `extracted/packs/<pack>/scenario/**` |
| 关系 / 时间线 / 概要 / 术语 | `knowledge/relationships.md`、`timeline.md`、`story_summary.md`、`glossary.md` |
| 各类报告 | `reports/`（提取、人物、错误、质量） |

## 二、数据规模

| 项目 | 数值 |
| --- | --- |
| 剧本文件（`.s`） | 402 |
| 正文消息 | 41919（台词 27840 / 旁白 14040 / 选项 38 / 章标题 1） |
| 场景 | 269 |
| 章节 | 3（本編 / アフター / エイプリル） |
| 说话人 | 105 |
| 选项点 | 19 |
| 多版本文件 | 437（全部保留原始版本） |

## 三、游戏与来源

- 游戏目录：`E:\gal\Navel\近月少女的礼仪`（本仓库不复制原始游戏文件，只记录路径）
- 引擎：**QLIE**（`FilePackVer3.0` 归档 + `key.fkey` + exe 内 GameKey）
- 剧本：归档内 `scenario\*.s`，Shift-JIS 明文 AVG 脚本
- 原始文件始终只读，本项目的任何操作都没有修改游戏目录

## 四、工具（可用来自行重跑）

```powershell
cd Galgame_AI_Knowledge\tools
python qlie.py list    "E:\gal\Navel\近月少女的礼仪\GameData\data0.pack" --exe "E:\gal\Navel\近月少女的礼仪\月に寄りそう乙女の作法.exe"
python extract_scripts.py     # 导出全部文本资源 + 合并视图 + 清单
python parse_scripts.py       # 解析成 raw/ 与 cleaned/ 两层
python analyze_characters.py  # 人物台词库与统计
python insights.py            # 语言特征、场景分布
python show_scene.py 本編/l12_03b   # 单场景朗读（写作/校对用）
python quality_check.py       # 生成质量报告
```

### 会话记录导出（`tools\export_session.mjs`，Node 脚本，非 Python）

把 DSH 任意会话的**完整原始对话**导出为可读 Markdown，供归档者按原文核对。
**只读**：不修改、移动或删除任何原始记录。

> **职责边界**：本工具**只负责导出、校验、分段、定位**——不判断剧情内容、不提取事件、
> 不更新任何长期档案。那些属于「归档者」会话的职责；工具相关的记录在 `reports\sessions\`，
> 与 `knowledge\` 下的剧情档案严格分开。

```powershell
$node = "C:\Users\salat\.workbuddy-ai\binaries\node\versions\22.22.2-2\node.exe"
& $node Galgame_AI_Knowledge\tools\export_session.mjs --list            # 列出全部会话
& $node Galgame_AI_Knowledge\tools\export_session.mjs --session <ID前缀>
& $node Galgame_AI_Knowledge\tools\export_session.mjs --session <ID> --out <目录> --split-every 20
& $node Galgame_AI_Knowledge\tools\export_session.mjs --lookup <seq> --index <名>.locate.md
```

每条消息都带稳定 ID `[#seq]`，分段导出后仍可用 `--lookup` 查回原文所在文件与行号。
用 Node 而非 Python：会话文件是**多帧 zstd 压缩 JSONL**，Python 标准库无 zstd，
Node 的 `node:zlib` 自带；因此该脚本零外部依赖。
全部说明（选项、产出文件、校验单、定位用法、脱敏与完整性检查）见 `PROJECT_STATE.md` 第 4 节。

### 双会话协作（扮演者 / 归档者）

项目采用**两个独立会话**协作：扮演者负责剧情与导出，归档者负责读取原始记录与维护长期档案。
职责、权限、交接流程与 Git 规则见 [`双会话协作规范.md`](双会话协作规范.md)（v1.1）；
**导出、校验、定位的确切命令**见 [`knowledge\reference\工具使用速查卡.md`](knowledge/reference/工具使用速查卡.md)。

> 工具使用速查卡与规范冲突时，**以速查卡的命令为准**。
> 两个会话都不执行 Git 提交；提交由用户决定。

依赖：仅 Python 3 标准库（无第三方包）。

## 五、数据分层（对应任务说明的结构）

```
original/    游戏原文件位置说明（不复制大文件）
extracted/   归档解包结果（逐 pack 原始副本 + 合并视图）
raw/         逐行原始记录（含指令、标签、控制码）
cleaned/     清洗后的可读文本（仅去控制码，不删信息）
script/      预留：按路线拆分的剧本导出
characters/  人物台词库（JSON）
knowledge/   AI 可读的知识层（人物档案、关系、时间线、概要、术语）
reports/     提取/人物/错误/质量报告
tools/       全部脚本
```

## 六、可追溯性

每条消息都带有：`file`（剧本路径）、`source_pack`（来自哪个 pack）、`line`（行号）、
`scene` / `chapter`、`speaker`、`text`；更进一步可回溯到
`reports/extract_manifest.json` 中的归档偏移与 MD5。

追溯链：**pack 文件 → 归档内偏移 → `.s` 行号 → 消息记录 → 人物台词库 → 人物档案**

## 七、已知限制

- 当前文本为**日文原文**。汉化补丁（KID Fans Club v1.21）的译文存放在被替换的 exe 尾部
  加密覆盖段中，尚未解析，详见 `reports/error_report.md`。
- 图像、音频、视频未导出（本次目标为剧本）。
- 作品版权归 Navel 所有；本知识库仅作个人学习、检索与角色扮演用途。

## 八、回退

每一步都有 Git 提交。要回到某个阶段：

```powershell
git -C C:\Users\salat\Desktop\git log --oneline
git -C C:\Users\salat\Desktop\git show <commit>:Galgame_AI_Knowledge/cleaned/messages.jsonl > messages.old.jsonl
```
