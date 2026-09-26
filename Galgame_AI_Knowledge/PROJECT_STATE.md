# PROJECT_STATE —— 交接记录

| 项目 | 内容 |
| --- | --- |
| 交接编号 | **HO-20260926-01** |
| 状态 | **材料已核对・等待接手核验**（接手任务尚未创建） |
| 源任务 | 当前 Codex 任务（工作目录 `C:\Users\salat\Desktop\git`） |
| 接手任务编号 | （未创建，留空） |
| 更新时间 | 2026-09-26 |

> 路径说明：以下路径均为**本机绝对路径**（Windows，用户 `salat`），跨机器不可直接用。
> 项目根目录 = `C:\Users\salat\Desktop\git\Galgame_AI_Knowledge`（下文简写为 `<KB>`）。

---

## 0. 新 AI 必读文件清单

### 第一层：**必读**（不读就无法正确接续）

| 顺序 | 文件（绝对路径） | 要查的内容 |
| --- | --- | --- |
| 1 | `<KB>\PROJECT_STATE.md` | 本文件：任务、限制、进度、接续动作 |
| 2 | `<KB>\README.md` | 项目总览、目录结构、工具用法、已知限制 |
| 3 | `<KB>\knowledge\characters\ookura_yuusei.md` | 小倉朝日／大蔵遊星的人物档案与**语体规则**（角色扮演的权威依据，含内部标签→第一人称对照表） |
| 4 | `<KB>\knowledge\characters\sakuragi_luna.md` | 桜小路ルナ 的人物档案与语体规则 |
| 5 | `C:\Users\salat\Desktop\git\.gitignore` | 游戏派生数据被排除的规则（改动前必看） |
| 6 | `C:\Users\salat\.codex\AGENTS.md` | 用户长期工作偏好：Git 优先、只做本地提交、不擅自 push |
| 7 | `C:\Users\salat\Downloads\Galgame_AI知识库构建任务说明.md` | 用户的原始方法论要求（二十一条 + 验收标准） |

### 第二层：按需查阅

| 文件 | 内容 |
| --- | --- |
| `<KB>\knowledge\glossary.md` | 专有名词、人物索引、**语体与称呼对照表**、剧本文法说明 |
| `<KB>\knowledge\timeline.md` | 路线结构（c/l/u/y/h 前缀含义）、全部 19 个选项点原文 |
| `<KB>\knowledge\relationships.md` | 关系图、称呼对照、共现统计 |
| `<KB>\knowledge\story_summary.md` | 剧情概要（自行撰写，非原文照抄） |
| `<KB>\reports\extraction_report.md` | 引擎识别、密钥机制、提取流程与产出清单 |
| `<KB>\reports\error_report.md` | **已知限制**与「可以放心引用的结论」清单 |
| `<KB>\reports\character_report.md` | 105 个说话人识别结果、主角标签拆分 |
| `<KB>\reports\quality_report.md` | 数据质量统计（41919 条消息等） |
| `<KB>\reports\insights.json` | 场景台词密度、句尾统计、称呼统计 |
| `<KB>\reports\character_stats.json` | 两位角色的语言特征（特征说法、句尾、第一人称） |

### 第三层：数据层（体积大，用脚本或按关键字检索，不要整份读入）

| 文件 | 内容 | 规模 |
| --- | --- | --- |
| `<KB>\cleaned\messages.jsonl` | **全剧本清洗层**：每条含 id / file / source_pack / line / chapter / scene / type / speaker / text / voice | 41919 条・23 MB |
| `<KB>\raw\script_lines.jsonl` | 逐行原文层（含指令、标签、内联控制码） | 171111 行・12 MB |
| `<KB>\characters\sakuragi_luna.json` | 露娜全部台词 | 4995 条・1.8 MB |
| `<KB>\characters\ookura_yuusei.json` | 朝日／遊星全部台词（带身份标签） | 8668 条・2.9 MB |
| `<KB>\characters\_all_speakers.json` | 105 个说话人索引 | 12 KB |
| `<KB>\extracted\merged\**` | 合并后的 `.s` 剧本（Shift-JIS 明文） | 696 个文件・229 MB |
| `<KB>\extracted\packs\<pack>\**` | 逐 pack 原始副本（多版本都保留） | 1660 个文件 |
| `<KB>\reports\extract_manifest.json` | 每个文件的来源 pack、归档偏移、MD5 | 393 KB |
| `<KB>\reports\pack_index\data*.txt` | 15 个 pack 的完整目录清单 | 2.7 MB |
| `<KB>\tools\*.py` | 7 个可重跑脚本（见下节） | —— |

### 第四层：游戏本体（**只读，禁止修改**）

| 路径 | 说明 |
| --- | --- |
| `E:\gal\Navel\近月少女的礼仪\` | 游戏根目录（汉化版 v1.21 + 原版 exe） |
| `E:\gal\Navel\近月少女的礼仪\GameData\data0..15.pack` | 15 个 `FilePackVer3.0` 归档，约 5.6 GB |
| `E:\gal\Navel\近月少女的礼仪\DLL\key.fkey` | 密钥文件（4146 字节） |
| `E:\gal\Navel\近月少女的礼仪\月に寄りそう乙女の作法.exe` | 原版 exe（GameKey 来源：`TFORM1 → IconKeyImage`） |
| `E:\gal\Navel\近月少女的礼仪\近月少女的礼仪_v1.21.exe` | 汉化 exe（尾部 6.6 MB 加密容器，**未解析**） |
| `E:\gal\Navel\【KID Fans Club汉化组】…（单独备份）\` | 汉化补丁 rar 备份（含 403 条目的线索） |

---

## 1. 任务与版本

| 项目 | 内容 |
| --- | --- |
| 总目标 | 按《Galgame_AI知识库构建任务说明》的方法，为《近月少女的礼仪》建立可检索、可追溯、供 AI 使用的结构化知识库 |
| 当前焦点 | 角色 **桜小路ルナ** 与 **大蔵遊星（小倉朝日）** |
| 完成标准（已完成部分） | 引擎确认 / 原始文件未破坏 / 剧本提取 / 角色识别 / 台词—旁白—选项区分 / 剧情顺序 / 分支处理 / 人物台词库 / 人物关系 / 时间线 / AI 可读数据 / 质量检查与错误报告 / 可 Git 回退 |
| 工作目录 | `C:\Users\salat\Desktop\git`（Git 仓库根）；项目目录 `<KB>` |
| 分支 / 提交 | `main`，最新提交 **0404c7e**（`feat(galgame-kb): …`） |
| 未提交改动 | 无（本文件 `PROJECT_STATE.md` 为本次交接写入） |

---

## 2. 权威资料的分工

| 资料 | 管理哪一部分 | 备注 |
| --- | --- | --- |
| `<KB>\extracted\merged\**`（`.s`，cp932） | **剧情原文的最终机读原点** | 由工具从 pack 解出，未改一个字节 |
| `<KB>\cleaned\messages.jsonl` | AI 检索层（台词/旁白/选项） | 由 `parse_scripts.py` 生成，可重跑复现 |
| `<KB>\raw\script_lines.jsonl` | 原始信息保全层 | 指令与标签都在 |
| `<KB>\knowledge\characters\*.md` | 人物解读（性格、语体、剧情） | 每条结论附脚本文件+行号 |
| `<KB>\knowledge\glossary.md` | 语体与称呼规则 | 角色扮演时的语体权威 |
| `C:\Users\salat\Downloads\Galgame_AI知识库构建任务说明.md` | 用户对方法与验收的要求 | 与本文冲突时以用户当场指示为准 |

无已知资料冲突。注意：`extracted\packs\` 与 `extracted\merged\` 的差异是**多版本覆盖关系**，不是矛盾（437 个文件存在多版本）。

---

## 3. 决定与限制

### 用户已确认

- 采用 **Git 优先**工作方式：改文件的收尾要本地提交并说明「动了哪些文件 / 关键差异 / 怎么回退」。
- **只做本地提交，不擅自 push / pull**；涉及网络需用户确认（出现确认提示属正常）。
- 原始游戏文件视为只读，不得修改、删除、覆盖。

### Agent 已执行的选择（用户未逐条否决）

- 引擎判定 **QLIE**、归档 `FilePackVer3.0`；密钥三来源：`DLL\key.fkey`、归档内 `pack_keyfile_*.key`、exe 内 GameKey（256 字节）。
- 多版本合并规则：**pack 序号大者优先**（`data0` → `data15`），全部版本另存不删。
- 剧本文法规则（解析依据）：`^指令` / `\指令` / `@标签` / `@@` / `@@@`、说话人 `【…】`、语音 `％v_xxx`、内联控制码 `[n] [0-15] [rb,…] [c,…]` 等。
- **`.gitignore` 排除了游戏派生数据**（`extracted/`、`raw/`、`cleaned/`、`characters/*.json`，约 650 MB）。理由：仓库 `origin` 是公开地址（`https://github.com/xujike009-collab/git.git`），避免把受版权保护的游戏文本推上公开仓库。
  - **⚠ 此项建议由用户确认**：若用户要连数据一起做本地版本控制，把 `.gitignore` 里那 4 行注释掉后重新提交即可（仍不要 push）。

### 未决 / 待确认

- 汉化中文文本是否要做（需先解析 exe 尾部容器）。
- 是否导出 CG／立绘／语音（工具已具备能力，本次未做）。
- 是否把游戏派生数据纳入 Git。

---

## 4. 进展与运行状态

### 已完成（含验证证据）

| 成果 | 证据位置 | 验证方式 |
| --- | --- | --- |
| 引擎与格式识别 | `reports\extraction_report.md` | exe 版本信息 + 解包成功（名字与正文可读） |
| 归档解包 | `extracted\packs\`、`extracted\merged\` | 1660 / 696 个文件，`reports\extract_manifest.json` 记录 MD5 |
| 剧本结构化 | `raw\script_lines.jsonl`（171111 行）、`cleaned\messages.jsonl`（41919 条） | `reports\parse_stats.json`：无法归类行 **0** |
| 角色识别 | `characters\*.json`、`reports\character_report.md` | 105 个说话人，来源为剧本自带 `【…】` 标签 |
| 人物资料 | `knowledge\characters\*.md` | 每条结论附脚本文件+行号 |
| 关系 / 时间线 / 术语 / 概要 | `knowledge\*.md` | 与用户本地攻略交叉验证 |
| 质量检查 | `reports\quality_report.md`、`error_report.md` | 乱码 0、空文本 0、解析失败 0 |

### 进行中

- **角色扮演会话**（无文件产物，状态记录在本文件第 5 节）。

### 未做

- 汉化中文译文提取；CG／立绘／语音导出；其余角色（湊／ユルシュール／瑞穂／衣遠／りそな）的独立档案；`script\` 目录按路线拆分导出。

### 可重跑的脚本（`<KB>\tools\`，仅需 Python 3 标准库）

```powershell
cd C:\Users\salat\Desktop\git\Galgame_AI_Knowledge\tools
python qlie.py list "E:\gal\Navel\近月少女的礼仪\GameData\data0.pack" --exe "E:\gal\Navel\近月少女的礼仪\月に寄りそう乙女の作法.exe"
python extract_scripts.py      # 解包 + 合并 + 清单
python parse_scripts.py        # raw/ 与 cleaned/ 两层
python analyze_characters.py   # 人物台词库与统计
python insights.py             # 语言特征与场景分布
python show_scene.py 本編/l12_03b   # 单场景朗读
python quality_check.py        # 质量报告
```

---

## 5. 角色扮演会话状态（接手需要知道全部细节）

### 设定（用户明确指定）

| 项目 | 内容 |
| --- | --- |
| 扮演对象 | **小倉朝日（大蔵遊星）**，时间点为他在桜小路宅邸当女仆的时期 |
| 用户身份 | **徐穗，男性**，长期借住樱公馆（桜小路家）的客人，服装设计同行 |
| 关系状态 | 两人在设计与日常交流中渐生好感；朝日因自己是男人而始终不敢表白；**徐穗不知道朝日的真实性别** |
| 场景 | 青山一带的咖啡馆，两人喝咖啡闲聊（第一幕已完成） |
| 当前线索 | 徐穗要**以朝日为主体设计一件衣服**，朝日私下当模特试穿；成品作为**只有两人知道的秘密** |

### 已达成的剧情节点（接续时不要重复）

1. 纸样信封：**外面写「徐穗」**（对外只是普通纸样），**内折页写「朝日の伙伴 徐穗」**（两人之间的秘密）。
2. 朝日答应「只在工房里、只穿给你一个人看」的私密试穿，并主动要求**自己报尺寸**（他会写一份伪造但可用的数据）。
3. 朝日要求**缝份留宽**，理由是日后可以自己偷偷收改到合身（隐藏真实体型）。
4. 朝日提出的最后一个问题（**球在用户手上，等待回答**）：
   > 「您画这件衣服的时候，看到的那个人，是工房里的朝日，还是别的人。」

### 输出格式规则（用户明确要求，务必遵守）

- **（　）= 心声**（内心独白，对应原作旁白层）
- **【　】= 台词**（真正说出口的话）
- **其余不加任何标记 = 动作与叙述**
- 代词：**徐穗一律用「他」**；朝日在第一人称叙述里用「我」；剧中不知情的人称朝日为「她」。

### 语体约束（有原文数据支撑，勿凭感觉改写）

- 朝日：全程敬语（日语「です／ます」，自称对应「私」）；被夸奖或被逼近时慌乱（高频「はい」「え？」）；习惯自嘲；**把感情塞进「工作／手续」的壳子里**；偶尔漏出**不加敬语的短句**——那是他真情流露的信号，用完通常会想补回去（有时不补 = 更深的破绽）。
- 对徐穗的称呼：「徐穗さん」级别；不加敬语的短句只在「宅邸之外、两人独处」时出现（用户已授权此场景）。
- 宅邸其他人物（露娜、ユルシュール、瑞穂、湊、八千代、衣遠等）的语体见 `knowledge\characters\*.md` 与 `knowledge\glossary.md`。
- 内容边界：**不要复制游戏原文长段**；必要短引用需注明出处；知识库本体保持日文原文。

---

## 6. 接续动作

### 建议的第一步（按当前重心二选一）

**A. 继续角色扮演（用户最近的动作）**

1. 读第 0 节第 1–4、6 项文件，确认与本节记录一致。
2. 从第 5 节第 4 条那个问题的答案处接续：用户会回应「画里看到的是谁」，据此推进咖啡馆这一幕或转入工房试穿。
3. 严守格式规则（（ ）心声 /【 】台词 / 无标记动作）与语体约束。
4. 验收：用户直接回复即视为验收；若走偏，用户会像前几轮那样提出「停，退出」并修正设定——**修正后要更新本文件第 5 节**。

**B. 继续知识库建设**

1. 候选：解析汉化 exe 尾部容器（403 条目、尾部魔数 `0xCAFEBABE`、6.6 MB 加密覆盖段），目标是拿到中文译文层。
2. 候选：为其余三位女主各建一份 `knowledge\characters\*.md`（数据已在 `characters\_all_speakers.json`）。
3. 候选：导出 CG／立绘／语音（`tools\qlie.py` 已能解 `ABMP／DPNG／ARGB／OGG／WAV`）。

### 前置条件与阻塞项

- 角色扮演：无阻塞。
- 汉化容器：可行性**未验证**，属逆向工作；需要时先做小规模探测，不要直接批量处理。
- 任何下载／联网动作需用户确认（沙箱可能要求批准）。

### 验收方法

- 角色扮演：用户在场逐轮反馈。
- 知识库：按第 4 节的脚本重跑，统计应与 `reports\quality_report.md` 一致（41919 条消息 / 台词 27840 / 旁白 14040 / 选项 38 / 说话人 105 / 场景 269 / 解析失败 0）。
- 回退：`git -C C:\Users\salat\Desktop\git log --oneline`，需要时 `git revert <commit>` 或 `git reset --hard 0404c7e`。

---

## 7. 开场白（可复制给新任务）

```text
$project-handoff

项目绝对路径：C:\Users\salat\Desktop\git\Galgame_AI_Knowledge
交接来源与编号：PROJECT_STATE.md，HO-20260926-01（源任务：近月少女的礼仪知识库 + 小倉朝日角色扮演）
当前目标：继续《近月少女的礼仪》知识库工作，并接续正在进行的「小倉朝日」角色扮演会话。
已确认限制：只读游戏原文件；Git 只做本地提交、不 push；知识库本体为日文原文；角色扮演遵守（ ）=心声、【 】=台词、无标记=动作的格式，且徐穗为男性（用「他」）。
可执行的第一步：先只读核对本文件的第 0 节必读清单（重点：PROJECT_STATE.md、README.md、knowledge\characters\ookura_yuusei.md、.gitignore、AGENTS.md），报告与记录不一致之处，不要改动文件。
验收方法：核验结果与第 5 节「角色扮演会话状态」一致后，从该节第 4 条的问题处继续对话；知识库侧可用 reports\quality_report.md 的统计复现验证。
```
