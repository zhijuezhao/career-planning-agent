/**
 * 详情预览工具（P1-1）
 *
 * 设计约定：
 * - **纯函数、无 IO、不依赖视图类型** —— 输入用最小结构类型，便于各页复用与单测。
 * - Markdown 渲染走自研极简解析（对齐学生端 `ReportMarkdown.vue` 的「不引入依赖」取舍），
 *   且**只产出文本节点、从不生成 HTML**，因此不存在 XSS 面。
 * - 解析逻辑放这里而不是组件里，是为了能脱离 Vue 单测（见 `tests` 或人工验证）。
 */

// ── Markdown 解析 ───────────────────────────────────────────────────────────

export type MarkdownBlock =
  | { kind: 'heading'; level: 1 | 2 | 3; text: string }
  | { kind: 'paragraph'; text: string }
  | { kind: 'quote'; text: string }
  | { kind: 'list'; ordered: boolean; items: { text: string; depth: number }[] }
  | { kind: 'code'; text: string; lang: string }

export interface InlineSegment {
  type: 'text' | 'bold' | 'code'
  text: string
}

const INLINE_RE = /(\*\*[^*]+\*\*|`[^`]+`)/g
const HEADING_RE = /^(#{1,3})\s+(.*)$/
const LIST_RE = /^(\s*)([-*]|\d+[.、])\s+(.*)$/

/** 行内语法切分：`**加粗**` 与 `` `行内代码` ``，其余为纯文本 */
export function inlineSegments(text: string): InlineSegment[] {
  const out: InlineSegment[] = []
  let last = 0

  for (const match of text.matchAll(INLINE_RE)) {
    const index = match.index ?? 0
    if (index > last) out.push({ type: 'text', text: text.slice(last, index) })

    const token = match[0]
    if (token.startsWith('**')) {
      out.push({ type: 'bold', text: token.slice(2, -2) })
    } else {
      out.push({ type: 'code', text: token.slice(1, -1) })
    }
    last = index + token.length
  }

  if (last < text.length) out.push({ type: 'text', text: text.slice(last) })
  return out
}

/**
 * 极简 Markdown 块解析。
 *
 * 支持：`#/##/###` 标题、`- * ` 无序与 `1. / 1、` 有序列表（2 空格缩进记一层级）、
 * `>` 引用、``` 围栏代码块、其余为段落（连续行合并）。
 */
export function parseMarkdown(raw: string | null | undefined): MarkdownBlock[] {
  const lines = (raw ?? '').replace(/\r\n?/g, '\n').split('\n')
  const blocks: MarkdownBlock[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i] ?? ''
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    // 围栏代码块（结束围栏缺失也容忍）
    if (trimmed.startsWith('```')) {
      const lang = trimmed.slice(3).trim()
      const buf: string[] = []
      i += 1
      while (i < lines.length && !(lines[i] ?? '').trim().startsWith('```')) {
        buf.push(lines[i] ?? '')
        i += 1
      }
      i += 1
      blocks.push({ kind: 'code', text: buf.join('\n'), lang })
      continue
    }

    const heading = HEADING_RE.exec(trimmed)
    if (heading) {
      const level = (heading[1] ?? '#').length as 1 | 2 | 3
      blocks.push({ kind: 'heading', level, text: (heading[2] ?? '').trim() })
      i += 1
      continue
    }

    if (trimmed.startsWith('>')) {
      blocks.push({ kind: 'quote', text: trimmed.replace(/^>\s?/, '') })
      i += 1
      continue
    }

    // 列表：连续的同类列表项合并成一个块（层级用 depth 表达，避免嵌套 <ul> 的解析复杂度）
    const listStart = LIST_RE.exec(line)
    if (listStart) {
      const ordered = /\d/.test(listStart[2] ?? '')
      const items: { text: string; depth: number }[] = []

      while (i < lines.length) {
        const m = LIST_RE.exec(lines[i] ?? '')
        if (!m || /\d/.test(m[2] ?? '') !== ordered) break
        items.push({
          text: (m[3] ?? '').trim(),
          depth: Math.floor((m[1] ?? '').length / 2),
        })
        i += 1
      }

      blocks.push({ kind: 'list', ordered, items })
      continue
    }

    // 段落：吃连续的非空、且不是其它块起始的行
    const buf: string[] = [trimmed]
    i += 1
    while (i < lines.length) {
      const nextLine = lines[i] ?? ''
      const next = nextLine.trim()
      if (
        !next ||
        next.startsWith('#') ||
        next.startsWith('```') ||
        next.startsWith('>') ||
        LIST_RE.test(nextLine)
      ) {
        break
      }
      buf.push(next)
      i += 1
    }
    blocks.push({ kind: 'paragraph', text: buf.join(' ') })
  }

  return blocks
}

// ── JSON → Markdown 投影 ────────────────────────────────────────────────────

export const EMPTY_TEXT = '（暂无）'

export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function isEmptyValue(value: unknown): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  if (isPlainObject(value)) return Object.keys(value).length === 0
  return false
}

/**
 * 任意 JSON 值 → Markdown。
 * 对象 → `- **键**：值`，数组 → `- 值`，嵌套结构再降一层（2 空格缩进）。
 */
export function jsonToMarkdown(value: unknown, depth = 0): string {
  if (isEmptyValue(value)) return EMPTY_TEXT

  const indent = '  '.repeat(depth)

  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (isEmptyValue(item)) return `${indent}- ${EMPTY_TEXT}`
        if (isPlainObject(item) || Array.isArray(item)) {
          return `${indent}-\n${jsonToMarkdown(item, depth + 1)}`
        }
        return `${indent}- ${String(item)}`
      })
      .join('\n')
  }

  if (isPlainObject(value)) {
    return Object.entries(value)
      .map(([key, val]) => {
        if (isEmptyValue(val)) return `${indent}- **${key}**：${EMPTY_TEXT}`
        if (isPlainObject(val) || Array.isArray(val)) {
          return `${indent}- **${key}**：\n${jsonToMarkdown(val, depth + 1)}`
        }
        return `${indent}- **${key}**：${String(val)}`
      })
      .join('\n')
  }

  return String(value)
}

// ── 岗位画像 ────────────────────────────────────────────────────────────────

export interface JobPortraitLike {
  hard_skills?: unknown
  soft_skills?: unknown
  requirement_intensity?: unknown
  career_path?: unknown
  transition_paths?: unknown
  outlook?: unknown
  summary?: unknown
}

export interface PortraitSection {
  key: keyof JobPortraitLike
  label: string
  markdown: string
  empty: boolean
}

const PORTRAIT_FIELDS: { key: keyof JobPortraitLike; label: string }[] = [
  { key: 'hard_skills', label: '硬技能' },
  { key: 'soft_skills', label: '软技能' },
  { key: 'requirement_intensity', label: '能力要求' },
  { key: 'career_path', label: '晋升路径' },
  { key: 'transition_paths', label: '转型路径' },
  { key: 'outlook', label: '发展前景' },
  { key: 'summary', label: '画像摘要' },
]

/** 岗位画像 → 逐字段的预览段落（前端投影，不新增存储） */
export function jobPortraitSections(job: JobPortraitLike): PortraitSection[] {
  return PORTRAIT_FIELDS.map(({ key, label }) => {
    const value = job[key]
    const empty = isEmptyValue(value)
    return {
      key,
      label,
      empty,
      markdown: empty
        ? EMPTY_TEXT
        : typeof value === 'string'
          ? value
          : jsonToMarkdown(value),
    }
  })
}

// ── 画像快照 ────────────────────────────────────────────────────────────────

export interface SnapshotLike {
  id: number
  user_id: number
  username?: string | null
  serial_no?: string | null
  description?: string | null
  matched?: boolean
  matched_at?: string | null
  created_at?: string | null
  six_dim_scores?: Record<string, number> | null
  five_layers?: Record<string, unknown> | null
}

/**
 * 快照 → 预览用 Markdown。
 *
 * 注意：**下载用的 .md 由后端渲染**（`snapshot_markdown.py`，含完整附录），
 * 这里只服务于弹窗预览，两者用途不同、不共享实现。
 */
export function snapshotMarkdown(snap: SnapshotLike): string {
  const lines: string[] = [`# 画像快照 ${snap.serial_no ?? snap.id}`, '']

  const meta: [string, unknown][] = [
    ['快照ID', snap.id],
    ['用户ID', snap.user_id],
    ['用户名', snap.username ?? undefined],
    ['描述', snap.description ?? undefined],
    ['生成时间', formatDateTime(snap.created_at)],
    ['匹配状态', snap.matched ? '已匹配' : '待匹配'],
    ['匹配时间', snap.matched_at ? formatDateTime(snap.matched_at) : undefined],
  ]
  for (const [label, value] of meta) {
    if (isEmptyValue(value)) continue
    lines.push(`- **${label}**：${String(value)}`)
  }

  const layers = snap.five_layers
  if (!isEmptyValue(layers)) {
    lines.push('', '## 五层画像', '')
    for (const [name, content] of Object.entries(layers ?? {})) {
      lines.push(`### ${name}`, '', jsonToMarkdown(content), '')
    }
  }

  const scores = snap.six_dim_scores
  if (!isEmptyValue(scores)) {
    lines.push('## 六维分数', '')
    for (const [name, score] of Object.entries(scores ?? {})) {
      lines.push(`- **${name}**：${score}`)
    }
  }

  return lines.join('\n').trimEnd()
}

// ── 杂项格式化 ──────────────────────────────────────────────────────────────

/** 错误列表 → Markdown 列表（导入失败原因、批量错误都用它） */
export function errorsToMarkdown(errors: unknown): string {
  if (isEmptyValue(errors)) return EMPTY_TEXT
  const list = Array.isArray(errors) ? errors : [errors]
  if (list.length === 0) return EMPTY_TEXT
  return list
    .map((item) => `- ${typeof item === 'string' ? item : JSON.stringify(item)}`)
    .join('\n')
}

export function formatBytes(bytes?: number | null): string {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', { hour12: false })
}

/** 进度百分比（total 为 0 时返回 0，避免 NaN 渗进进度条） */
export function progressPercent(processed?: number | null, total?: number | null): number {
  if (!total || total <= 0) return 0
  const pct = ((processed ?? 0) / total) * 100
  return Math.max(0, Math.min(100, Math.round(pct)))
}
