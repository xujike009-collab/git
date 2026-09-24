# 提取报告

## 一、游戏与引擎识别

| 项目 | 结果 | 证据 |
| --- | --- | --- |
| 游戏 | 月に寄りそう乙女の作法（近月少女的礼仪 / Navel, 汉化：KID Fans Club v1.21） | 目录 `E:\gal\Navel\近月少女的礼仪` |
| 引擎 | **QLIE**（Delphi 制作的视觉小说引擎） | 可执行文件版本信息 `Product=QLIE / FileDescription=QLIE / OriginalFilename=IMOSURUME / FileVersion=1.10.0.0`；程序内部字符串 `TImoScript` `ImoScriptLib` `filepackver3.0` `KeyFile ver1.0` |
| 归档格式 | `FilePackVer3.0`（15 个 `data*.pack`，合计约 5.6 GB） | 每个 pack 末尾 0x1C 字节明文尾标 |
| 密钥机制 | 1) `DLL\key.fkey`（4146 字节）；2) 归档内条目 `pack_keyfile_*.key`（解出后替换 fkey）；3) 从 exe 窗体资源 `TFORM1 → IconKeyImage → Picture.Data` 取出 256 字节 GameKey | 解包成功后名字与正文均正常，可反向验证 |
| 剧本形式 | **明文的 Shift-JIS 脚本**（扩展名 `.s`，AVG 指令 + 台词文本混排） | `scenario\本編\c00_01a.s` 首行 `@@@AVG\header.s` |

> 判断依据全部经过实际验证：用上述密钥解出的 402 个 `.s` 文件内容连贯可读，
> 与攻略、语音编号、图像路径互相印证，因此引擎与格式的判定不是猜测。

## 二、提取流程

1. `tools/qlie.py` —— QLIE 归档只读读取器（Parsing `FilePackVer3.0` 索引、条目解密、
   `1PC\xFF` LZ 解压、从 exe 中取 GameKey）。算法依据公开开源实现 GARbro（MIT）的 QLIE 模块转写。
2. `tools/extract_scripts.py` —— 遍历 15 个 pack，导出全部文本类资源（`.s .txt .b .dat .key .csv`），
   产出 `extracted/packs/<pack>/…`（逐 pack 原始副本）与 `extracted/merged/…`（后 pack 覆盖前 pack 的合并视图），
   并写出 `reports/extract_manifest.json`（含归档偏移、大小、MD5、是否加密压缩）。
3. `tools/parse_scripts.py` —— 解析为结构化数据：`raw/script_lines.jsonl`（每一行，含指令与标签）与
   `cleaned/messages.jsonl`（台词 / 旁白 / 选项 / 章标题）。
4. `tools/analyze_characters.py`、`tools/insights.py`、`tools/quality_check.py` —— 人物台词库与统计、
   语言特征、质量检查。

## 三、产出清单

| 产出 | 内容 | 规模 |
| --- | --- | --- |
| `extracted/packs/**` | 每个 pack 的文本类资源原始副本 | 1660 个文件 |
| `extracted/merged/**` | 按加载顺序合并后的版本 | 696 个文件（229 MB） |
| `raw/script_lines.jsonl` | 逐行原始记录（含指令、标签、内联控制码） | 171111 行 |
| `cleaned/messages.jsonl` | 可读文本层 | 41919 条 |
| `characters/*.json` | 台词库（含全部说话人索引） | 105 个说话人 |
| `reports/*.json` | 抽取清单、解析统计、人物统计、质量检查 | 4 份 |

## 四、多版本处理

同一脚本在多个 pack 中出现（例如 `scenario\本編\c00_01a.s` 同时存在于 data6/9/10/11）。
本项目的处理方式是：

- 全部版本都保留在 `extracted/packs/<pack>/`，不覆盖、不删除；
- 合并视图按 **pack 序号大者优先**（`data0` → `data15`），并记录在清单里；
- 437 个文本资源存在多版本，差异可在 `reports/extract_manifest.json` 中逐一比对 MD5。

> 备注：`data0` 内的 `pack_keyfile_kfueheish15538fa9or.key` 与 `DLL\key.fkey` 大小相同（4146 字节），
> 是 QLIE 的归档级替换密钥，已按格式处理，未写入最终数据集。

## 五、未做的事（有意为之）

- **没有修改任何原始游戏文件**：所有操作都是只读，输出全部落在项目目录。
- **没有提取图像与音频**：本次目标是剧本与人物资料；如需 CG/语音可另开一步（工具已具备能力）。
- **没有提取汉化文本**：汉化补丁 v1.21 的译文不在 pack 中，而是加密存放在被替换的 exe 尾部
  （6.6 MB 覆盖段，尾部魔数 `0xCAFEBABE` 的 KFC 自定义容器）。当前未破解该容器，
  因此本知识库是**日文原文**版本。详见 `reports/error_report.md`。
