#!/usr/bin/env node
/**
 * export_session.mjs —— 把 DSH 会话的原始记录导出为可读的 Markdown
 *
 * 用途：
 *   扮演者会话结束后，把完整原始对话导出成 Markdown，供归档者按原文核对与归档。
 *   本工具只【读取】DSH 的会话文件，绝不修改、移动或删除任何原始记录。
 *
 * 为什么用 Node 而不是 Python：
 *   DSH 的会话文件是「多帧拼接的 zstd 压缩 JSONL」（session.vN.jsonl.zstd）。
 *   Python 标准库没有 zstd，需要额外安装 zstandard 模块；
 *   而 Node 内置的 node:zlib 自带 zstd 解压。因此本脚本零外部依赖，
 *   用 WorkBuddy 自带的 Node 即可运行。
 *
 * 用法：
 *   node export_session.mjs --list
 *        列出本机所有可导出的会话（含工作区、消息数、修改时间、文件大小）
 *
 *   node export_session.mjs --session <ID或ID前缀>
 *        导出指定会话。可用会话 ID 前缀，例如 --session e6fd23f1
 *
 *   node export_session.mjs --session <ID> --out <输出路径或目录>
 *        指定输出位置。若给的是目录，则自动生成文件名。
 *
 *   node export_session.mjs --lookup <seq>
 *        按消息 ID 定位：显示该 ID 属于哪个 Turn、落在哪个分段文件、是哪种消息
 *
 *   node export_session.mjs --all --out <目录>
 *        批量导出全部会话
 *
 *   node export_session.mjs --assistants
 *        列出本机的「扮演者/助手」代理预设，便于确认导出对象
 *
 * 职责边界（重要）：
 *   本工具**只负责导出、校验、分段、定位**。
 *   它不判断剧情内容、不提取事件、不更新任何长期档案——
 *   那些属于「归档者」会话的职责，不在本工具范围内。
 *   每条消息都带原始事件序号（ID）`[#seq]`，分段导出后仍可用它追溯回原始事件。
 *
 * 常用选项：
 *   --no-thinking     不包含模型思考过程（默认包含，便于核对推理依据）
 *   --tool-detail N   工具调用保留的名称+摘要；N 为摘要字符上限（默认 200）
 *   --split-every N   分段导出：每 N 个 Turn 一个文件，并生成 <名>.index.md 进度表
 *                     （供归档者分段读取、逐段记录已读范围；默认 0 = 不分段）
 *   --redact          开启自动脱敏（默认已开启；此开关用于显式声明）
 *   --no-redact       关闭自动脱敏（默认不推荐）
 *   --stdout          输出到标准输出而不写文件
 *   --index <文件>    配合 --lookup 使用，指定 .locate.md 定位索引的路径
 *   --home <路径>     覆盖 DSH_HOME
 *   -h, --help        显示本帮助
 *
 * 会话文件位置：
 *   <DSH_HOME>/sessions/<工作区名>/<会话ID>/session.vN.jsonl.zstd
 *   DSH_HOME 默认取环境变量 DSH_HOME；也可用 --home <路径> 覆盖。
 *
 * 产出文件（--split-every N 时）：
 *   <名>.md                完整合并记录
 *   <名>.turn-NNN-MMM.md   分段文件（每段自带文件头，可独立阅读）
 *   <名>.index.md          分段索引 + 读取进度表
 *   <名>.locate.md         消息定位索引（ID → 文件与行号）
 *   SESSION-EXPORT-<会话ID>.sha256  旁置校验单（用 Get-FileHash 比对）
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import zlib from 'node:zlib';
import crypto from 'node:crypto';

/** 计算文件或缓冲区的 SHA-256（用于归档校验值）。 */
function sha256Of(input) {
  const h = crypto.createHash('sha256');
  h.update(Buffer.isBuffer(input) ? input : fs.readFileSync(input));
  return h.digest('hex');
}

// ---------------------------------------------------------------- 参数解析

const argv = process.argv.slice(2);
function opt(name, fallback = undefined) {
  const i = argv.indexOf(name);
  if (i === -1) return fallback;
  const v = argv[i + 1];
  return (v === undefined || v.startsWith('--')) ? true : v;
}
function has(name) { return argv.includes(name); }

const HOME = opt('--home') || process.env.DSH_HOME ||
  path.join(os.homedir(), 'WorkBuddy AI', 'Claw', '.dsh-home');
const SESSION_ROOT = path.join(HOME, 'sessions');
const TOOL_SUMMARY_LIMIT = Number(opt('--tool-detail', 200)) || 200;
/** 分段导出的粒度：每 N 个 Turn 一个文件（0 = 不分段）。 */
const SPLIT_EVERY = Number(opt('--split-every', 0)) || 0;
const INCLUDE_THINKING = !has('--no-thinking');
const REDACT = has('--redact') || !has('--no-redact');
const TO_STDOUT = has('--stdout');

// ---------------------------------------------------------------- zstd 帧扫描
// DSH 的会话文件是「一帧一批事件」的拼接容器。这里按 zstd 的真实帧结构
// （帧魔数 + 帧头 + 块头）逐帧定位，再逐帧同步解压，避免把压缩数据里
// 偶然出现的魔数误当成帧边界。

const ZSTD_MAGIC = 4247762216;

function scanZstdFrames(buf) {
  const frames = [];
  let off = 0;
  while (off < buf.length) {
    const start = off;
    if (buf.length - off < 4) break;
    if (buf.readUInt32LE(off) !== ZSTD_MAGIC) break;
    off += 4;
    const desc = buf.readUInt8(off); off += 1;
    if ((desc & 24) !== 0) throw new Error(`帧头保留位异常 @${off - 1}`);
    const contentSizeFlag = desc >>> 6;
    const singleSegment = (desc & 32) !== 0;
    const checksum = (desc & 4) !== 0;
    const dictFlag = desc & 3;
    const dictBytes = dictFlag === 3 ? 4 : dictFlag;
    const csBytes = contentSizeFlag === 0 ? (singleSegment ? 1 : 0) : 1 << contentSizeFlag;
    off += (singleSegment ? 0 : 1) + dictBytes + csBytes;
    for (;;) {
      if (buf.length - off < 3) return frames;
      const bh = buf.readUIntLE(off, 3); off += 3;
      const last = (bh & 1) !== 0;
      const type = (bh >>> 1) & 3;
      const size = bh >>> 3;
      if (type === 3) throw new Error(`块类型保留值异常 @${off - 3}`);
      const payload = type === 1 ? 1 : size;
      if (buf.length - off < payload) return frames;
      off += payload;
      if (last) break;
    }
    if (checksum) off += 4;
    frames.push([start, off]);
  }
  return frames;
}

function readSessionJsonl(file) {
  const buf = fs.readFileSync(file);
  if (!zlib.zstdDecompressSync) {
    throw new Error('当前 Node 不支持 zstd（需要 Node >= 22.15）。请用 WorkBuddy 自带 Node 运行。');
  }
  const frames = scanZstdFrames(buf);
  if (frames.length === 0) throw new Error('未找到任何 zstd 帧，文件可能损坏或格式已变更');
  const parts = [];
  let failed = 0;
  for (const [a, b] of frames) {
    try { parts.push(zlib.zstdDecompressSync(buf.subarray(a, b))); }
    catch { failed++; }
  }
  const text = Buffer.concat(parts).toString('utf8');
  const events = [];
  let badLines = 0;
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try { events.push(JSON.parse(line)); } catch { badLines++; }
  }
  return { events, stats: { frames: frames.length, failedFrames: failed, badLines, sourceSha256: sha256Of(buf) } };
}

// ---------------------------------------------------------------- 会话定位

function listSessions() {
  const out = [];
  if (!fs.existsSync(SESSION_ROOT)) return out;
  for (const ws of fs.readdirSync(SESSION_ROOT)) {
    const wsDir = path.join(SESSION_ROOT, ws);
    if (!fs.statSync(wsDir).isDirectory()) continue;
    for (const sid of fs.readdirSync(wsDir)) {
      const dir = path.join(wsDir, sid);
      if (!fs.statSync(dir).isDirectory()) continue;
      const file = fs.readdirSync(dir).find((f) => f.endsWith('.jsonl.zstd') || f.endsWith('.jsonl'));
      if (!file) continue;
      const full = path.join(dir, file);
      out.push({
        workspace: ws.replace(/^--|--$/g, ''),
        id: sid,
        dir,
        file: full,
        bytes: fs.statSync(full).size,
        mtime: fs.statSync(full).mtime,
      });
    }
  }
  return out.sort((a, b) => b.mtime - a.mtime);
}

function resolveSession(idOrPrefix) {
  const all = listSessions();
  const exact = all.find((s) => s.id === idOrPrefix);
  if (exact) return exact;
  const hits = all.filter((s) => s.id.startsWith(idOrPrefix) || s.id.includes(idOrPrefix));
  if (hits.length === 1) return hits[0];
  if (hits.length > 1) {
    throw new Error(`会话前缀 "${idOrPrefix}" 匹配到 ${hits.length} 个，请给更长的前缀：\n` +
      hits.map((h) => `  ${h.id}  (${h.workspace})`).join('\n'));
  }
  throw new Error(`找不到会话 "${idOrPrefix}"。用 --list 查看可用会话。`);
}

// ---------------------------------------------------------------- 脱敏
// 归档记录可能进入版本库或长期档案，因此默认对常见凭据形态做脱敏。

const REDACT_RULES = [
  // 明确的 key=value 形态（含 yaml / json / 环境变量赋值）
  // 只保留极短前缀，便于归档者区分不同凭据，又不泄漏足够位数。
  [/\b(sk-[A-Za-z0-9])[A-Za-z0-9_-]{6,}/g, '$1…[已脱敏]'],
  [/((?:api[_-]?key|apikey|secret|token|password|passwd|pwd)\s*["':=]\s*["']?)([A-Za-z0-9_\-.]{12,})/gi, '$1[已脱敏]'],
  // 常见厂商前缀
  [/\b(ghp_|gho_|ghu_|ghs_|github_pat_)[A-Za-z0-9_]{10,}/g, '$1[已脱敏]'],
  [/\bxox[baprs]-[A-Za-z0-9-]{10,}/g, 'xox[已脱敏]'],
  [/\bAKIA[0-9A-Z]{12,}/g, 'AKIA[已脱敏]'],
  [/\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/g, '[JWT 已脱敏]'],
  // UUID 形态的 key（Exa 一类）：整体只留前 6 位
  [/\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi, (m) => m.slice(0, 6) + '…[已脱敏]'],
  // 长随机串兜底。必须跳过纯十六进制串：SHA-256/MD5 校验值、提交号、十六进制
  // 摘要都是这个形态，它们不是密钥，却是归档校验的依据——脱敏掉会让校验失效。
  [/\b[A-Za-z0-9_\-]{40,}\b/g, (m) => /^[0-9a-f]+$/i.test(m) ? m : '[长字符串已脱敏]'],
];

function redact(s) {
  if (!REDACT || typeof s !== 'string') return s;
  let out = s;
  for (const [re, rep] of REDACT_RULES) out = out.replace(re, rep);
  return out;
}

// ---------------------------------------------------------------- Markdown 生成

/**
 * user/message 事件里哪些才是「人真正说的」。
 *
 * DSH 会把多种系统上下文以 user/message 的形式注入（每轮的记忆快照、后台任务
 * 通知、模型切换提示、AGENTS.md、技能目录等）。实测一轮长对话里这些注入能占
 * 到 87% 的字符量，若与真人发言混在一起，归档者会被淹没。
 * 这里按 data.source.kind 区分：user 才是人说的，其余各自标注来源。
 */
const USER_KINDS = new Set(['user']);
const INJECTION_LABEL = {
  'dsh-mnemon': 'Mnemon 记忆协议注入',
  'tool-jobs': '后台任务通知',
  'model-selection': '模型切换通知',
  'agent-instructions': '工作区指令注入（AGENTS.md 等）',
  'runtime-context': '运行时上下文注入',
  'skill-catalog': '技能目录注入',
};

function injectionLabel(kind) {
  if (!kind) return '系统注入（未标注来源）';
  return INJECTION_LABEL[kind] || `系统注入（${kind}）`;
}

function fmtTime(ms) {
  if (!ms) return '';
  try { return new Date(ms).toLocaleString('zh-CN', { hour12: false }); } catch { return String(ms); }
}

function oneLine(s, limit) {
  if (s === undefined || s === null) return '';
  const t = String(s).replace(/\s+/g, ' ').trim();
  return t.length > limit ? t.slice(0, limit) + ` …（截断，原长 ${t.length}）` : t;
}

/** 把工具参数压成一行摘要：优先取 description / command / 首个值 */
function summarizeArgs(argStr) {
  if (!argStr) return '';
  let obj = null;
  try { obj = JSON.parse(argStr); } catch { return oneLine(argStr, TOOL_SUMMARY_LIMIT); }
  if (obj && typeof obj === 'object') {
    for (const k of ['description', 'prompt', 'query', 'command', 'file_path', 'pattern', 'input']) {
      if (typeof obj[k] === 'string' && obj[k].trim()) {
        return `\`${k}\`: ${oneLine(obj[k], TOOL_SUMMARY_LIMIT)}`;
      }
    }
    const keys = Object.keys(obj);
    if (keys.length) return `参数键: ${keys.join(', ')}`;
  }
  return oneLine(argStr, TOOL_SUMMARY_LIMIT);
}

function fence(text) {
  // 选择不会与正文冲突的围栏长度
  let n = 3;
  while (new RegExp('^`{' + n + '}', 'm').test(text)) n++;
  const f = '`'.repeat(n);
  return `${f}text\n${text}\n${f}`;
}

function convert(session, events) {
  const splitEvery = SPLIT_EVERY;
  const lines = [];
  const turnStarts = []; // 每个 Turn 在 lines 里的起始索引，用于分段导出
  const turnList = [];   // { turn, seq, startLine }：供定位索引使用
  const locIndex = [];   // 每条消息级事件的定位记录：{ seq, turn, kind, line }
  let turnNo = 0;
  /**
   * 记录一条消息级事件的定位。
   * 关键：必须传入「该事件标题行」在 lines 里的索引——若在 push 之前记录，
   * 由于一个事件会推入多行正文，误差会逐条累积，索引彻底失真。
   */
  const mark = (ev, kind, line) => locIndex.push({ seq: ev.seq, turn: turnNo, kind, line });
  const header = events.find((e) => e.type === 'session');
  let turns = 0, userMsgs = 0, assistantMsgs = 0, toolCalls = 0, toolResults = 0, injectedMsgs = 0;
  const warnings = [];
  const pendingCalls = new Map(); // callId -> {name, args}
  const seenCallIds = new Set();

  lines.push(`# 会话记录：${session.id}`);
  lines.push('');
  lines.push('| 项目 | 值 |');
  lines.push('| --- | --- |');
  lines.push(`| 会话 ID | \`${session.id}\` |`);
  lines.push(`| 工作区 | \`${session.workspace}\` |`);
  if (header?.cwd) lines.push(`| 会话 cwd | \`${header.cwd}\` |`);
  if (header?.agentPreset) lines.push(`| 代理预设 | \`${header.agentPreset}\` |`);
  lines.push(`| 起始时间 | ${fmtTime(events.find((e) => e.time)?.time)} |`);
  lines.push(`| 导出时间 | ${fmtTime(Date.now())} |`);
  lines.push(`| 原始文件 | \`${session.file}\` |`);
  lines.push(`| 原始大小 | ${(session.bytes / 1024 / 1024).toFixed(2)} MB（解压后事件 ${events.length} 条） |`);
  lines.push(`| 脱敏 | ${REDACT ? '已开启' : '**已关闭**'} |`);
  lines.push('');
  lines.push('> 本文件由 `tools/export_session.mjs` 从 DSH 原始会话文件导出。');
  lines.push('> 原始记录只被读取，未被修改。');
  lines.push('');
  lines.push('---');
  lines.push('');

  for (const ev of events) {
    const d = ev.data || {};
    switch (ev.type) {
      case 'session':
        break;

      case 'session/title': {
        const title = d.title || d.text || d.name;
        if (title) { lines.push(`**会话标题**：${redact(String(title))}`); lines.push(''); }
        break;
      }

      case 'turn/start': {
        turnStarts.push(lines.length);
        turns++;
        turnNo = turns;
        turnList.push({ turn: turnNo, seq: ev.seq, startLine: lines.length });
        locIndex.push({ seq: ev.seq, turn: turnNo, kind: 'turn/start', line: lines.length });
        lines.push(`## Turn ${turns}　<span title="${fmtTime(ev.time)}"></span>`);
        lines.push('');
        break;
      }

      case 'user/message': {
        const kind = d.source?.kind || '';
        const isHuman = USER_KINDS.has(kind);
        const parts = d.content || [];
        // 只负责渲染文本与附件；标题行按是否真人发言分别处理
        const renderParts = () => {
          if (!parts.length) {
            lines.push('*（空消息）*'); lines.push('');
            warnings.push(`第 ${ev.seq} 条 user/message 无 content`);
            return;
          }
          for (const p of parts) {
            if (p.type === 'text') {
              lines.push(redact(p.text || ''));
              lines.push('');
            } else if (p.type === 'image' || p.type === 'attachment') {
              const a = p.attachment || p;
              lines.push(`*（图片/附件：\`${a.name || a.attachmentId || '未知'}\`，${a.bytes || '?'} 字节）*`);
              lines.push('');
            } else {
              lines.push(`*（附件类型：${p.type}）*`); lines.push('');
            }
          }
        };

        if (isHuman) {
          userMsgs++;
          lines.push(`### 👤 用户 \`[#${ev.seq}]\`　<sub>${fmtTime(ev.time)}</sub>`);
          mark(ev, 'user/message', lines.length - 1);
          lines.push('');
          renderParts();
        } else {
          injectedMsgs++;
          const textLen = parts.filter((p) => p.type === 'text')
            .reduce((a, p) => a + (p.text || '').length, 0);
          lines.push(`<details><summary>⚙️ [#${ev.seq}] ${injectionLabel(kind)}（${textLen} 字符，非用户发言）</summary>`);
          mark(ev, `injected:${kind || 'unknown'}`, lines.length - 1);
          lines.push('');
          renderParts();
          lines.push('</details>');
          lines.push('');
        }
        break;
      }

      case 'assistant/message': {
        assistantMsgs++;
        lines.push(`### 🤖 助手 \`[#${ev.seq}]\`　<sub>${fmtTime(ev.time)}</sub>`);
        mark(ev, 'assistant/message', lines.length - 1);
        lines.push('');
        const msg = d.message || {};
        for (const p of msg.content || []) {
          if (p.type === 'reasoning') {
            if (INCLUDE_THINKING && p.text) {
              lines.push('<details><summary>💭 思考过程</summary>');
              lines.push('');
              lines.push(redact(p.text));
              lines.push('');
              lines.push('</details>');
              lines.push('');
            }
          } else if (p.type === 'text') {
            const t = redact(p.text || '');
            if (t.trim()) { lines.push(t); lines.push(''); }
          } else if (p.type === 'tool-call') {
            toolCalls++;
            seenCallIds.add(p.id);
            pendingCalls.set(p.id, { name: p.name, args: p.arguments });
            lines.push(`#### 🔧 调用工具 \`${p.name}\``);
            mark(ev, `tool-call:${p.name}`, lines.length - 1);
            const sum = summarizeArgs(p.arguments);
            if (sum) { lines.push(`> ${redact(sum)}`); lines.push(''); }
          }
        }
        break;
      }

      case 'tool/call': {
        // assistant/message 已记录同一调用时跳过，避免重复
        if (!seenCallIds.has(d.callId)) {
          toolCalls++;
          lines.push(`#### 🔧 调用工具 \`${d.name}\``);
          mark(ev, `tool-call:${d.name}`, lines.length - 1);
          const sum = summarizeArgs(d.arguments);
          if (sum) { lines.push(`> ${redact(sum)}`); lines.push(''); }
        }
        break;
      }

      case 'tool/result': {
        toolResults++;
        const txt = (d.message?.content || [])
          .filter((c) => c.type === 'text').map((c) => c.text).join('\n');
        // 配对字段在 data.message.toolCallId（不是 data 顶层）；source.callId 作为兜底。
        const callId = d.message?.toolCallId || d.message?.source?.callId || d.toolCallId;
        const call = pendingCalls.get(callId);
        const label = call ? `\`${call.name}\`` : '（无法配对到调用）';
        if (!call) {
          warnings.push(`第 ${ev.seq} 条 tool/result 找不到配对的 tool/call` +
            `（callId=${callId ?? 'undefined'}；data.message 字段: ${Object.keys(d.message || {}).join(',')}）`);
        }
        lines.push(`<details><summary>📤 工具结果 ${label} \`[#${ev.seq}]\`（${txt.length} 字符）</summary>`);
        mark(ev, `tool-result:${call ? call.name : 'unknown'}`, lines.length - 1);
        lines.push('');
        lines.push(fence(redact(txt || '（空）')));
        lines.push('');
        lines.push('</details>');
        lines.push('');
        break;
      }

      case 'approval/asked': {
        lines.push(`#### ⚠️ 审批请求 \`[#${ev.seq}]\``);
        mark(ev, 'approval/asked', lines.length - 1);
        lines.push(`> ${redact(oneLine(d.description || d.prompt || JSON.stringify(d).slice(0, 200), 300))}`);
        lines.push('');
        break;
      }

      case 'approval/answered': {
        lines.push(`> ✅ 审批结果：${redact(String(d.decision || d.outcome || d.answer || '已处理'))}`);
        lines.push('');
        break;
      }

      case 'turn/end': {
        locIndex.push({ seq: ev.seq, turn: turnNo, kind: 'turn/end', line: lines.length });
        lines.push('');
        lines.push('---');
        lines.push('');
        break;
      }

      default:
        break; // 其余事件（步骤/重试/遥测等）不计入正文
    }
  }

  // 统计与完整性报告
  const stat = [
    '',
    '---',
    '',
    '## 导出完整性报告',
    '',
    '| 项目 | 数量/结果 |',
    '| --- | --- |',
    `| Turn 数 | ${turns} |`,
    `| 用户消息（人真正说的） | ${userMsgs} |`,
    `| 系统注入消息（已折叠） | ${injectedMsgs} |`,
    `| 助手消息 | ${assistantMsgs} |`,
    `| 工具调用 | ${toolCalls} |`,
    `| 工具结果 | ${toolResults} |`,
    `| 总事件条数 | ${events.length} |`,
    `| 原始文件 SHA-256 | \`${session.sourceSha256}\` |`,
    '| 本文件校验值 | 见同目录 `SESSION-EXPORT-<会话ID>.sha256`（哈希无法写入被哈希的文件自身） |',
  ];
  lines.push(...stat);
  if (warnings.length) {
    lines.push('');
    lines.push('### ⚠️ 需要人工核对的问题');
    lines.push('');
    for (const w of warnings) lines.push(`- ${w}`);
  } else {
    lines.push('');
    lines.push('未发现无法解析或无法配对的内容。');
  }
  lines.push('');

  // 分段导出：按每 N 个 Turn 切一刀，便于归档者分次读取并记录进度。
  // 分段取自「含 [#seq] 标记的完整文档」的同一份行数组，因此每条消息的 ID
  // 在各段中都被原样保留；某段的行号 = 全局行号 - 该段起始全局行号 + 1。
  const segRanges = [];
  const segments = [];
  if (splitEvery > 0 && turnStarts.length > 0) {
    for (let s = 0; s < turnStarts.length; s += splitEvery) {
      const firstTurn = s + 1;
      const lastTurn = Math.min(s + splitEvery, turnStarts.length);
      const bodyStart = turnStarts[s];
      const nextStart = (s + splitEvery < turnStarts.length) ? turnStarts[s + splitEvery] : lines.length;
      const segPrefix = [
        ...lines.slice(0, turnStarts[0]),
        `## 本文件范围：Turn ${firstTurn} – ${lastTurn}（共 ${turnStarts.length} 个 Turn）`,
        '',
        '> 这是分段导出文件。归档时请在本段读完后，把「已读取 Turn 范围」记录到归档进度中。',
        '> 本段内每条消息都保留原始事件 ID `[#seq]`，可用它追回原始对话。',
        '',
      ];
      const segLines = [...segPrefix, ...lines.slice(bodyStart, nextStart)];
      segments.push({ firstTurn, lastTurn, md: segLines.join('\n') });
      segRanges.push({
        firstTurn, lastTurn, bodyStart, nextStart,
        segPrefixLen: segPrefix.length, // 前缀长度取决于文件头行数，必须实算
        segLineCount: segLines.length,
      });
    }
  }

  // 定位索引：每个 [#seq] 落在哪个 Turn、哪个分段、第几行。
  //
  // 行号一律**从生成的正文里扫描得出**，而不是依赖渲染过程中维护的计数器——
  // 计数器写法一旦错位就会逐条累积偏差（我踩过这个坑），扫描正文则天然与产出
  // 文件一致，不可能漂移。
  const anchorAt = new Map(); // seq -> 完整文件行号（1 基）
  lines.forEach((l, i) => {
    const m = l.match(/\[#(\d+)\]/);
    if (m) {
      const q = Number(m[1]);
      if (!anchorAt.has(q)) anchorAt.set(q, i + 1);
    }
  });

  const locLines = locIndex.map((x) => {
    const masterLine = anchorAt.get(x.seq) ?? (x.line + 1);
    // 段内行号同样由扫描得到的行号逆推，保证与完整文件行号同源、不漂移。
    let file = null; let line = masterLine;
    const idx0 = masterLine - 1;
    for (const r of segRanges) {
      if (idx0 >= r.bodyStart && idx0 < r.nextStart) {
        file = `turn-${String(r.firstTurn).padStart(3, '0')}-${String(r.lastTurn).padStart(3, '0')}.md`;
        line = idx0 - r.bodyStart + r.segPrefixLen + 1;
        break;
      }
    }
    return { seq: x.seq, turn: x.turn, kind: x.kind, masterLine, file, line };
  });

  return {
    markdown: lines.join('\n'),
    segments,
    segRanges,
    locLines,
    counts: { turns, userMsgs, injectedMsgs, assistantMsgs, toolCalls, toolResults },
    warnings,
  };
}

// ---------------------------------------------------------------- 主流程

function humanSize(b) {
  return b > 1024 * 1024 ? (b / 1024 / 1024).toFixed(2) + ' MB' : (b / 1024).toFixed(0) + ' KB';
}

/**
 * 按消息 ID 反查定位：从 `<名>.locate.md` 的表格里找出该 ID 属于哪个 Turn、
 * 落在哪个分段文件的第几行。只读索引文件，不触碰原始会话数据。
 */
function cmdLookup(seq, indexArg) {
  if (!indexArg || indexArg === true) {
    console.error('用法：--lookup <seq> --index "<会话ID>.locate.md 的路径"');
    console.error('先用 --session <ID> --split-every N 导出，会生成 <名>.locate.md。');
    process.exit(2);
  }
  if (!fs.existsSync(indexArg)) {
    console.error(`索引文件不存在：${indexArg}`);
    process.exit(2);
  }
  const text = fs.readFileSync(indexArg, 'utf8');
  const want = String(seq).replace(/^#/, '');
  const rows = text.split('\n').filter((l) => l.startsWith('| `#'));
  const hit = rows.find((l) => (l.match(/^\| `#(\d+)`/) || [])[1] === want);
  if (!hit) {
    console.error(`索引里找不到 ID #${want}（共 ${rows.length} 条记录）。`);
    process.exit(1);
  }
  const cells = hit.split('|').map((c) => c.trim()).filter((c) => c !== '');
  console.log(`消息 ID   : ${cells[0]}`);
  console.log(`类型      : ${cells[1]}`);
  console.log(`所属 Turn : ${cells[2]}`);
  console.log(`段文件    : ${cells[3]}`);
  console.log(`段内行号  : ${cells[4]}`);
  console.log(`完整文件行: ${cells[5]}  （未分段时的行号）`);
  console.log(`索引来源  : ${indexArg}`);
}

function cmdList() {
  const all = listSessions();
  console.log(`DSH_HOME: ${HOME}`);
  console.log(`共 ${all.length} 个会话\n`);
  console.log('会话 ID'.padEnd(46) + '修改时间'.padEnd(20) + '大小'.padEnd(10) + '工作区');
  console.log('-'.repeat(110));
  for (const s of all) {
    const id = s.id.length > 44 ? s.id.slice(0, 41) + '...' : s.id;
    console.log(id.padEnd(46) + s.mtime.toLocaleString('zh-CN', { hour12: false }).padEnd(20) +
      humanSize(s.bytes).padEnd(10) + s.workspace);
  }
  console.log('\n导出：node export_session.mjs --session <ID 或前缀>');
}

function exportOne(s, outArg) {
  const { events, stats } = readSessionJsonl(s.file);
  s.sourceSha256 = stats.sourceSha256;

  // 单遍生成即可：校验值走旁置清单（把哈希写进被哈希的文件自身在数学上不成立）。
  const final = convert(s, events);

  let target = null;
  if (!TO_STDOUT) {
    const safeId = s.id.replace(/[^\w.-]/g, '_');
    const defaultName = `session-${safeId}.md`;
    if (outArg && outArg !== true) {
      target = fs.existsSync(outArg) && fs.statSync(outArg).isDirectory()
        ? path.join(outArg, defaultName)
        : outArg;
    } else {
      target = path.join(s.dir, defaultName);
    }
    const outDir = path.dirname(target);
    fs.mkdirSync(outDir, { recursive: true });
    const finalMd = final.markdown;
    fs.writeFileSync(target, finalMd, 'utf8');
    const mainSha = sha256Of(Buffer.from(finalMd, 'utf8'));

    // 分段文件（--split-every > 0）
    const segInfo = [];
    if (final.segments.length) {
      const base = path.basename(target, '.md');
      for (const seg of final.segments) {
        const segMd = seg.md + '\n';
        const segName = `${base}.turn-${String(seg.firstTurn).padStart(3, '0')}-${String(seg.lastTurn).padStart(3, '0')}.md`;
        const segPath = path.join(outDir, segName);
        fs.writeFileSync(segPath, segMd, 'utf8');
        segInfo.push({
          name: segName,
          firstTurn: seg.firstTurn,
          lastTurn: seg.lastTurn,
          bytes: Buffer.byteLength(segMd),
          sha256: sha256Of(Buffer.from(segMd, 'utf8')),
        });
      }
      // 分段索引：归档者据此逐段读取并记录进度
      const idx = [
        `# 分段索引：${s.id}`,
        '',
        `- 完整合并文件：\`${path.basename(target)}\`（${(Buffer.byteLength(finalMd) / 1024).toFixed(1)} KB）`,
        `- 完整文件 SHA-256：\`${mainSha}\``,
        `- 原始会话文件：\`${s.file}\``,
        `- 原始文件 SHA-256：\`${stats.sourceSha256}\``,
        `- 分段粒度：每 ${SPLIT_EVERY} 个 Turn 一个文件，共 ${segInfo.length} 段`,
        '',
        '## 读取进度表（归档者逐段勾选；不要预先勾选未读的段）',
        '',
        '| 段 | 文件名 | Turn 范围 | 大小 | SHA-256 | 已读取 |',
        '| --- | --- | --- | --- | --- | --- |',
        ...segInfo.map((g, i) =>
          `| ${i + 1} | \`${g.name}\` | ${g.firstTurn}–${g.lastTurn} | ${(g.bytes / 1024).toFixed(1)} KB | \`${g.sha256.slice(0, 16)}…\` | ☐ |`),
        '',
        '> 完整校验值见同目录的 `SESSION-EXPORT-<会话ID>.sha256`，用标准命令即可独立验证。',
        '> 全部段读完、且重要事件已核对后，才可标记归档完成。',
        '',
      ].join('\n');
      fs.writeFileSync(path.join(outDir, `${base}.index.md`), idx, 'utf8');

      // 消息定位索引：ID → Turn / 分段文件 / 行号。
      //
      // 行号一律**从刚落盘的文件里扫描得出**，不用渲染过程中的任何计数器。
      // 计数器写法一旦错位就会逐条累积偏差（我在此踩过坑），而扫描落盘文件
      // 天然与产出完全一致，原理上不可能漂移。
      const readAnchors = (filePath) => {
        const map = new Map();
        fs.readFileSync(filePath, 'utf8').split('\n').forEach((l, i) => {
          const m = l.match(/\[#(\d+)\]/);
          if (m) { const q = Number(m[1]); if (!map.has(q)) map.set(q, i + 1); }
        });
        return map;
      };
      const masterAnchors = readAnchors(target);
      const segAnchors = new Map();
      for (const g of segInfo) segAnchors.set(g.name, readAnchors(path.join(outDir, g.name)));

      const loc = [
        `# 消息定位索引：${s.id}`,
        '',
        `- 完整文件：\`${path.basename(target)}\``,
        `- 分段粒度：每 ${SPLIT_EVERY} 个 Turn 一段，共 ${segInfo.length} 段`,
        '- 用法：在记录里看到 `[#1234]` 这类 ID，就在下表查它落在哪个文件第几行',
        '- 也可反向使用：`node export_session.mjs --lookup <seq> --index "<本文件路径>"`',
        '',
        '| ID | 类型 | Turn | 段文件 | 段内行 | 完整文件行 |',
        '| --- | --- | --- | --- | --- | --- |',
        ...final.locLines.map((x) => {
          const masterLine = masterAnchors.get(x.seq) ?? '';
          let file = '—'; let line = '';
          for (const [name, map] of segAnchors) {
            if (map.has(x.seq)) { file = name; line = map.get(x.seq); break; }
          }
          return '| `#' + x.seq + '` | ' + x.kind + ' | ' + x.turn + ' | ' +
            (file === '—' ? '—' : '`' + file + '`') + ' | ' + line + ' | ' + masterLine + ' |';
        }),
        '',
        '> 行号由导出完成后**扫描落盘文件**得出，与文件内容严格一致。',
        '> `turn/start`、`turn/end` 两类事件本身不带锚点标记，故其行号栏为空。',
        '',
      ].join('\n');
      fs.writeFileSync(path.join(outDir, `${base}.locate.md`), loc, 'utf8');
    }

    // 旁置校验单：哈希不能写进被哈希的文件自身，因此单独成文件。
    //
    // 文件名带会话 ID：早期版本用固定的 SESSION-EXPORT.sha256，后一次导出会覆盖
    // 前一次的校验单，导致旧批次再也无法校验（实际发生过）。按会话 ID 命名后
    // 多批可并存、互不覆盖。
    const manName = `SESSION-EXPORT-${s.id}.sha256`;
    const man = [
      '# 导出校验单（' + manName + '）',
      '',
      `- 会话 ID：\`${s.id}\``,
      `- 导出时间：${new Date().toISOString()}`,
      `- 原始会话文件：\`${s.file}\``,
      `- 原始文件 SHA-256：\`${stats.sourceSha256}\``,
      `- 原始文件大小：${s.bytes} 字节`,
      `- zstd 帧：${stats.frames}（失败 ${stats.failedFrames}，坏行 ${stats.badLines}）`,
      `- 导出统计：Turn ${final.counts.turns} / 用户 ${final.counts.userMsgs} / 注入 ${final.counts.injectedMsgs} / 助手 ${final.counts.assistantMsgs} / 工具调用 ${final.counts.toolCalls} / 工具结果 ${final.counts.toolResults}`,
      '',
      '## 导出文件校验值（sha256sum 格式）',
      '',
      `${mainSha}  ${path.basename(target)}`,
      ...segInfo.map((g) => `${g.sha256}  ${g.name}`),
      '',
      '## 如何验证',
      '',
      '```powershell',
      `cd ${outDir}`,
      'Get-FileHash *.md -Algorithm SHA256 | Format-Table Hash,Path',
      `# 或（装了 coreutils 的环境）：sha256sum -c ${manName}`,
      '```',
      '',
      '> 校验值与上述文件逐一比对；不一致说明文件被改动过，应暂停归档并报告。',
      '> 注意：原始会话文件在会话进行中仍会被追加写入，因此「原始文件 SHA-256」只在导出那一刻成立；',
      '> 若导出后原话继续产生新事件，重新导出会得到不同的原始哈希，属正常。',
      '',
    ].join('\n');
    fs.writeFileSync(path.join(outDir, manName), man, 'utf8');

    console.log(`会话      : ${s.id}`);
    console.log(`工作区    : ${s.workspace}`);
    console.log(`zstd 帧   : ${stats.frames}（失败 ${stats.failedFrames}，坏行 ${stats.badLines}）`);
    console.log(`解压后    : ${(Buffer.byteLength(finalMd) / 1024).toFixed(1)} KB`);
    console.log(`统计数据  : Turn ${final.counts.turns} / 用户 ${final.counts.userMsgs} / 注入 ${final.counts.injectedMsgs} / 助手 ${final.counts.assistantMsgs} / 工具调用 ${final.counts.toolCalls} / 工具结果 ${final.counts.toolResults}`);
    console.log(`原始 SHA256: ${stats.sourceSha256}`);
    console.log(`导出 SHA256: ${mainSha}`);
    if (segInfo.length) console.log(`分段      : ${segInfo.length} 段（每 ${SPLIT_EVERY} Turn）+ index.md`);
    console.log(`校验单    : ${path.join(outDir, manName)}`);
    if (final.warnings.length) console.log(`⚠️ 待核对  : ${final.warnings.length} 条`);
    console.log(`已写出    : ${target}`);
    console.log(`原始文件  : ${s.file}（只读，未修改）`);
    return;
  }
  process.stdout.write(final.markdown);
}

function main() {
  if (has('--help') || has('-h') || argv.length === 0) {
    // 从源码首部的块注释提取帮助文本：剥掉 /** 与 */，去掉每行前导的「 * 」，
    // 并截到注释结束为止——避免把代码行或残留符号一起打出来。
    const src = fs.readFileSync(new URL(import.meta.url), 'utf8').split('\n');
    const out = [];
    for (let i = 0; i < src.length; i++) {
      const l = src[i];
      if (i === 0 && l.trim().startsWith('/**')) continue;
      if (l.trim() === '*/') break;
      if (!/^\s*\*/.test(l)) continue;
      out.push(l.replace(/^\s*\* ?/, ''));
    }
    console.log(out.join('\n'));
    return;
  }
  if (has('--list')) return cmdList();
  if (has('--lookup')) return cmdLookup(opt('--lookup'), opt('--index'));

  if (has('--assistants')) {
    const seen = new Map();
    for (const s of listSessions()) {
      try {
        const { events } = readSessionJsonl(s.file);
        const h = events.find((e) => e.type === 'session');
        if (h?.agentPreset) seen.set(h.agentPreset, (seen.get(h.agentPreset) || 0) + 1);
      } catch { /* 跳过不可读的 */ }
    }
    console.log('本机代理预设（会话数）：');
    for (const [k, v] of [...seen].sort((a, b) => b[1] - a[1])) console.log(`  ${k.padEnd(28)} ${v}`);
    return;
  }

  const outArg = opt('--out');

  if (has('--all')) {
    const all = listSessions();
    console.log(`批量导出 ${all.length} 个会话...\n`);
    for (const s of all) {
      try { exportOne(s, outArg); }
      catch (e) { console.log(`  ✗ ${s.id}: ${e.message}`); }
      console.log('');
    }
    return;
  }

  const id = opt('--session');
  if (!id || id === true) {
    console.error('缺少 --session <ID>。用 --list 查看可用会话，或 --all 批量导出。');
    process.exit(2);
  }
  exportOne(resolveSession(id), outArg);
}

main();
