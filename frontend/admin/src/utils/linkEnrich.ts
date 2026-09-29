/**
 * 链接富化统计的前端投影（B3-3）
 *
 * 为什么单独抽成纯函数模块、而不是直接写进 `Import.vue`：下面每一条文案都对应后端
 * 一个具体口径，写错就等于让人**读错数据**。抽出来能脱离 Vue 复核，也便于别处复用。
 *
 * ⚠️ 以下五条口径**已于 2026-09-29 与用户逐条对齐**，别顺手改回去：
 *
 * 1. `rows_enriched` 只是「至少抓到一个页面」的行数，**不代表补到了字段** ——
 *    页面可能只有不可填的 `title`（见后端 `merge.py` 的 `LINKABLE_FIELDS`），
 *    或干脆什么都没提取到。真正回答「富化有没有用」的是 `rows_fields_filled`。
 *    **两个数必须一起出现**，否则会把"白抓了一堆页面"读成"补上了数据"。
 * 2. `jsonld_hits` / `og_hits` / `text_hits` 是**页级**计数且**可重叠**：一个页面
 *    可以同时命中三层，所以三者之和**可以大于** `urls_fetched`。标注必须写明。
 * 3. `template_hits` 的单位是**「页 × 字段」次**（每用模板成功补到一个字段记一次），
 *    **不是**"命中了几个模板"；`templates_learned` 是**写入的字段模板数**，包含
 *    "覆盖更新已有模板"，因此不全是新建。
 * 4. `budget_exceeded` 是 URL 上限与 LLM 上限的**或**，单独看**说不清撞了哪个** ——
 *    UI 一律显示拆分后的 `budget_url_exceeded` / `budget_llm_exceeded`；只有老数据
 *    （B3-3 之前写入的 stats）没有拆分键时，才回退到 `budget_exceeded`。
 * 5. `http_hits` 与 `urls_fetched` 在服务端**恒等**（`service.py` 同一处自增），
 *    所以只显示一个「实抓页数」，不再单列 `http_hits`（它仍会出现在 JSON 页签里）。
 */

export interface LinkEnrichStats {
  /** 总开关（`LINK_ENRICH_ENABLED`）。false 时下面的数字全是 0，别当"跑了但没效果"读 */
  enabled?: boolean
  rows_scanned?: number
  rows_with_url?: number
  rows_enriched?: number
  rows_fields_filled?: number
  rows_budget_skipped?: number
  urls_found?: number
  urls_unique?: number
  urls_fetched?: number
  cache_hits?: number
  http_hits?: number
  jsonld_hits?: number
  og_hits?: number
  text_hits?: number
  fields_filled?: Record<string, number>
  conflicts_count?: number
  conflicts?: unknown[]
  blocked?: unknown[]
  errors?: string[]
  budget_exceeded?: boolean
  budget_url_exceeded?: boolean
  budget_llm_exceeded?: boolean
  template_hits?: number
  templates_learned?: number
  llm_calls?: number
  tokens_used?: number
  tokens_input?: number
  tokens_output?: number
  llm_domains?: string[]
  llm_skipped?: Record<string, number>
}

/** 可被链接填充的字段 → 中文（与后端 `merge.py::LINKABLE_FIELDS` + `title` 对齐） */
export const FIELD_LABELS: Record<string, string> = {
  company: '公司',
  city: '城市',
  region: '省份',
  salary: '薪资',
  industry: '行业',
  level: '职级',
  education_requirement: '学历要求',
  experience_requirement: '经验要求',
  description: '岗位描述',
  requirements: '任职要求',
  // 不可填（去重键），列在这里只为万一出现在统计里时能显示中文
  title: '岗位名称',
}

export function fieldLabel(key: string): string {
  return FIELD_LABELS[key] ?? key
}

/** L3 没调用模型的原因（后端 `llm_extract.py` 只有这三个取值） */
export const LLM_SKIP_LABELS: Record<string, string> = {
  no_candidates: '本页没有可用候选定位式',
  budget: '预算用尽，已停止后续调用',
  error: '模型调用失败',
}

// ── 格式化 ──────────────────────────────────────────────────────────────────

/** 千分位（页数 / token 这类数字一眼看清量级） */
export function formatCount(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '0'
  return value.toLocaleString('en-US')
}

/** token 的紧凑写法：`950` → `950`、`1644` → `1.6k`、`12345` → `12k` */
export function formatTokensCompact(value?: number | null): string {
  const n = Number(value ?? 0) || 0
  if (n < 1000) return String(n)
  if (n < 10_000) return `${(n / 1000).toFixed(1)}k`
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`
  return `${(n / 1_000_000).toFixed(1)}M`
}

/** 是否发生了预算截断（含老数据的笼统标志） */
export function isTruncated(stats?: LinkEnrichStats | null): boolean {
  if (!stats) return false
  return Boolean(stats.budget_url_exceeded || stats.budget_llm_exceeded || stats.budget_exceeded)
}

// ── 表格单元格 ──────────────────────────────────────────────────────────────

export interface EnrichCell {
  text: string
  /** 是否发生了预算截断（表格里给个警示色） */
  truncated: boolean
}

/** 导入列表「链接富化」列的紧凑摘要；没有这份统计时返回 null（该列显示占位） */
export function enrichCell(stats?: LinkEnrichStats | null): EnrichCell | null {
  if (!stats) return null
  if (stats.enabled === false) return { text: '未启用', truncated: false }

  const fetched = stats.urls_fetched ?? 0
  const unique = stats.urls_unique ?? 0
  const calls = stats.llm_calls ?? 0
  const tokens = stats.tokens_used ?? 0

  const parts = [`${fetched}/${unique} 页`]
  parts.push(calls > 0 ? `LLM ${calls} 次` : '零 LLM')
  if (tokens > 0) parts.push(`${formatTokensCompact(tokens)} tok`)

  return { text: parts.join(' · '), truncated: isTruncated(stats) }
}

// ── 预算标志（拆分后） ──────────────────────────────────────────────────────

export interface BudgetFlag {
  label: string
  hit: boolean
}

/**
 * 预算截断的两个来源。
 *
 * 拆分键缺失（B3-3 之前写入的 stats）时只给一条笼统结论 —— 不能瞎猜是哪一个，
 * 因为 `budget_exceeded` 本身就是"或"，推断出来的归因会是错的。
 */
export function budgetFlags(stats?: LinkEnrichStats | null): BudgetFlag[] {
  const s = stats ?? {}
  const hasSplit = s.budget_url_exceeded !== undefined || s.budget_llm_exceeded !== undefined

  if (!hasSplit) {
    return [{ label: '触达预算上限（老数据未区分来源）', hit: Boolean(s.budget_exceeded) }]
  }
  return [
    { label: 'URL 上限（行数 / 链接数）', hit: Boolean(s.budget_url_exceeded) },
    { label: 'LLM 上限（调用次数 / token）', hit: Boolean(s.budget_llm_exceeded) },
  ]
}

// ── 指标分组（弹窗「专门展示」的主体） ──────────────────────────────────────

export interface EnrichMetric {
  label: string
  value: string
  /** 口径说明：容易读错的字段必须写 */
  hint?: string
  tone?: 'default' | 'good' | 'warn'
}

export interface EnrichMetricGroup {
  title: string
  /** 组级口径说明 */
  note?: string
  metrics: EnrichMetric[]
}

const n = (value?: number | null): number => Number(value ?? 0) || 0

export function enrichMetricGroups(stats?: LinkEnrichStats | null): EnrichMetricGroup[] {
  const s = stats ?? {}

  // 两个来源**都要列**：同时撞上 URL 上限与 LLM 上限是可能的
  const hitSources: string[] = []
  if (s.budget_url_exceeded) hitSources.push('URL 上限')
  if (s.budget_llm_exceeded) hitSources.push('LLM 上限')
  // 老数据（拆分键缺席）只能给笼统结论
  if (!('budget_url_exceeded' in s) && !('budget_llm_exceeded' in s) && s.budget_exceeded) {
    hitSources.push('有（老数据未区分来源）')
  }
  const budgetValue = hitSources.length > 0 ? hitSources.join(' + ') : '未截断'

  return [
    {
      title: '总览',
      metrics: [
        { label: 'LLM 调用', value: `${formatCount(s.llm_calls)} 次`, hint: '每个域最多学一次；同域后续页面零调用' },
        {
          label: 'Token 消耗',
          value: formatCount(s.tokens_used),
          hint: `输入 ${formatCount(s.tokens_input)} / 输出 ${formatCount(s.tokens_output)}`,
        },
        {
          label: '模板命中',
          value: `${formatCount(s.template_hits)} 次`,
          hint: '单位是「页 × 字段」次，不是模板条数',
          tone: n(s.template_hits) > 0 ? 'good' : 'default',
        },
        {
          label: '学到字段模板',
          value: `${formatCount(s.templates_learned)} 条`,
          hint: '写入的字段模板数（含覆盖更新，不全是新建）',
        },
        {
          label: '预算截断',
          value: budgetValue,
          hint: 'URL 上限由上传行数决定；LLM 上限由表里有几个域决定',
          tone: isTruncated(s) ? 'warn' : 'default',
        },
      ],
    },
    {
      title: '抓取与缓存',
      metrics: [
        { label: '发现链接', value: formatCount(s.urls_found) },
        { label: '去重后链接', value: formatCount(s.urls_unique) },
        { label: '实抓页数', value: formatCount(s.urls_fetched), hint: '真实出网抓取的页数（不含缓存命中）' },
        {
          label: '缓存命中',
          value: formatCount(s.cache_hits),
          hint: '命中缓存的页面，零网络开销',
          tone: n(s.cache_hits) > 0 ? 'good' : 'default',
        },
      ],
    },
    {
      title: '三级提取命中',
      note: '按页计，可重叠 —— 一个页面可以同时命中多层，故三者之和可能大于实抓页数',
      metrics: [
        { label: 'JSON-LD', value: formatCount(s.jsonld_hits) },
        { label: 'OG 元标签', value: formatCount(s.og_hits) },
        { label: '正文', value: formatCount(s.text_hits) },
      ],
    },
    {
      title: '行级产出',
      note: '「已抓到页面的行」只是抓取成功，不代表补到了字段 —— 要看下一项',
      metrics: [
        { label: '扫描行数', value: formatCount(s.rows_scanned) },
        { label: '含链接的行', value: formatCount(s.rows_with_url) },
        {
          label: '已抓到页面的行',
          value: formatCount(s.rows_enriched),
          hint: '抓取成功即可，可能一个字段都没补到',
        },
        {
          label: '真正补到字段的行',
          value: formatCount(s.rows_fields_filled),
          hint: '至少补到 1 个字段的行数 —— 这才是富化的实际产出',
          tone: n(s.rows_fields_filled) > 0 ? 'good' : 'default',
        },
        {
          label: '超出行数上限',
          value: formatCount(s.rows_budget_skipped),
          hint: '因 LINK_ENRICH_MAX_ROWS 被跳过的行',
          tone: n(s.rows_budget_skipped) > 0 ? 'warn' : 'default',
        },
      ],
    },
  ]
}

// ── 明细行 ──────────────────────────────────────────────────────────────────

export interface FieldFillRow {
  field: string
  label: string
  count: number
}

/** 补全字段 → 按行数倒序（「哪些字段真被补上了」是富化价值最直接的证据） */
export function fieldFillRows(stats?: LinkEnrichStats | null): FieldFillRow[] {
  const map = stats?.fields_filled ?? {}
  return Object.entries(map)
    .map(([field, count]) => ({ field, label: fieldLabel(field), count: Number(count) || 0 }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label))
}

export interface SkipRow {
  key: string
  label: string
  count: number
}

/** L3 跳过原因 → 按次数倒序（回答"为什么这次没学到模板"） */
export function llmSkipRows(stats?: LinkEnrichStats | null): SkipRow[] {
  const map = stats?.llm_skipped ?? {}
  return Object.entries(map)
    .map(([key, count]) => ({ key, label: LLM_SKIP_LABELS[key] ?? key, count: Number(count) || 0 }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
}

/** 被 SSRF 守卫拦下的地址（安全件的可见证据） */
export function blockedEntries(stats?: LinkEnrichStats | null): string[] {
  return (stats?.blocked ?? []).map((item) =>
    typeof item === 'string' ? item : JSON.stringify(item),
  )
}

export function conflictEntries(stats?: LinkEnrichStats | null): string[] {
  return (stats?.conflicts ?? []).map((item) =>
    typeof item === 'string' ? item : JSON.stringify(item),
  )
}

// ── 可复制的 Markdown 摘要 ──────────────────────────────────────────────────

/** 弹窗预览用的 Markdown 摘要（与面板同源，便于复制到汇报里） */
export function enrichMarkdown(stats?: LinkEnrichStats | null): string {
  if (!stats) return ''
  const s = stats

  if (s.enabled === false) {
    return [
      '**本次导入未做链接富化**',
      '',
      `- 总开关 \`LINK_ENRICH_ENABLED\` 未开启（扫描 ${formatCount(s.rows_scanned)} 行）`,
      '- 打开总开关后重新导入即可看到富化统计',
    ].join('\n')
  }

  const lines: string[] = []
  for (const group of enrichMetricGroups(s)) {
    lines.push(`## ${group.title}`, '')
    if (group.note) lines.push(`> ${group.note}`, '')
    for (const metric of group.metrics) {
      const hint = metric.hint ? `（${metric.hint}）` : ''
      lines.push(`- **${metric.label}**：${metric.value}${hint}`)
    }
    lines.push('')
  }

  const fields = fieldFillRows(s)
  lines.push('## 补全字段', '')
  if (fields.length === 0) {
    lines.push('- （没有字段被补全）')
  } else {
    for (const row of fields) lines.push(`- **${row.label}**（\`${row.field}\`）：${row.count} 行`)
  }
  lines.push('')

  const skips = llmSkipRows(s)
  if (skips.length > 0) {
    lines.push('## L3 跳过原因', '')
    for (const row of skips) lines.push(`- ${row.label}：${row.count} 次`)
    lines.push('')
  }

  const domains = s.llm_domains ?? []
  if (domains.length > 0) {
    lines.push('## 学过模板的域', '', ...domains.map((d) => `- ${d}`), '')
  }

  const counts: string[] = []
  if (n(s.conflicts_count) > 0) counts.push(`表格值 vs 链接值冲突 ${formatCount(s.conflicts_count)} 条`)
  if ((s.blocked ?? []).length > 0) counts.push(`被安全守卫拦下 ${(s.blocked ?? []).length} 个地址`)
  if ((s.errors ?? []).length > 0) counts.push(`错误 ${(s.errors ?? []).length} 条`)
  if (counts.length > 0) {
    lines.push('## 需要留意', '', ...counts.map((c) => `- ${c}`))
  }

  return lines.join('\n').trimEnd()
}

/** 弹窗头部的标签 */
export interface EnrichTag {
  text: string
  type: 'primary' | 'success' | 'info' | 'warning' | 'danger'
}

export function enrichTags(stats?: LinkEnrichStats | null): EnrichTag[] {
  if (!stats) return []
  if (stats.enabled === false) return [{ text: '未启用', type: 'info' }]

  const tags: EnrichTag[] = [
    { text: `实抓 ${formatCount(stats.urls_fetched)} 页`, type: 'info' },
    { text: `补到字段 ${formatCount(stats.rows_fields_filled)} 行`, type: 'success' },
  ]
  if (n(stats.template_hits) > 0) tags.push({ text: `模板命中 ${formatCount(stats.template_hits)}`, type: 'success' })
  tags.push({
    text: `${formatCount(stats.llm_calls)} 次 LLM · ${formatCount(stats.tokens_used)} tok`,
    type: 'primary',
  })
  if (isTruncated(stats)) tags.push({ text: '预算截断', type: 'warning' })
  if ((stats.errors ?? []).length > 0) tags.push({ text: `${(stats.errors ?? []).length} 个错误`, type: 'danger' })
  return tags
}
