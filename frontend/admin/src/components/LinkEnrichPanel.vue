<script setup lang="ts">
/**
 * 链接富化统计面板（B3-3）
 *
 * 「专门展示」的主体：把 `data_import_jobs.stats.link_enrich` 从通用 JSON 页签里
 * 拎出来，按**口径分组**渲染 —— 总览 / 抓取与缓存 / 三级命中 / 行级产出 /
 * 补全字段 / 跳过原因 / 需要留意。
 *
 * 设计约定：
 * - 所有文案与数字都来自 `@/utils/linkEnrich`（纯函数），本组件只负责排版；
 *   那五条容易读错口径的说明写在该模块头部，改口径请改那里。
 * - 它挂在 `DetailDialog` 的 `preview-extra` 插槽里，因此**不自己包 dialog**。
 */
import { computed } from 'vue'
import {
  blockedEntries,
  budgetFlags,
  conflictEntries,
  enrichMetricGroups,
  fieldFillRows,
  llmSkipRows,
  type LinkEnrichStats,
} from '@/utils/linkEnrich'

const props = defineProps<{ stats?: LinkEnrichStats | null }>()

const groups = computed(() => enrichMetricGroups(props.stats))
const fields = computed(() => fieldFillRows(props.stats))
const skips = computed(() => llmSkipRows(props.stats))
const budgets = computed(() => budgetFlags(props.stats).filter((flag) => flag.hit))
const domains = computed(() => props.stats?.llm_domains ?? [])

const conflicts = computed(() => conflictEntries(props.stats))
const blocked = computed(() => blockedEntries(props.stats))
const errors = computed(() => props.stats?.errors ?? [])

/** 面板里每条明细最多列几项（完整内容在 JSON 页签里） */
const PREVIEW_LIMIT = 5

const preview = (items: string[]): string[] => items.slice(0, PREVIEW_LIMIT)

const hasIssues = computed(
  () => conflicts.value.length > 0 || blocked.value.length > 0 || errors.value.length > 0,
)
</script>

<template>
  <div class="lep">
    <el-alert
      v-if="!stats"
      type="info"
      :closable="false"
      show-icon
      title="本次导入没有链接富化统计"
      description="该任务可能是在链接富化功能上线前导入的。"
    />

    <el-alert
      v-else-if="stats.enabled === false"
      type="info"
      :closable="false"
      show-icon
      title="本次导入未做链接富化"
      :description="`总开关 LINK_ENRICH_ENABLED 未开启（已扫描行数 ${stats.rows_scanned ?? 0}）。打开开关后重新导入即可。`"
    />

    <template v-else>
      <div v-if="budgets.length > 0" class="lep-banner">
        <el-alert
          type="warning"
          :closable="false"
          show-icon
          title="本次触达预算上限，富化被截断（不是失败）"
          :description="`来源：${budgets.map((b) => b.label).join('；')}。已得到的规则结果照常保留。`"
        />
      </div>

      <section v-for="group in groups" :key="group.title" class="lep-group">
        <div class="lep-group-head">
          <span class="lep-group-title">{{ group.title }}</span>
          <span v-if="group.note" class="lep-group-note">{{ group.note }}</span>
        </div>
        <div class="lep-metrics">
          <div
            v-for="metric in group.metrics"
            :key="metric.label"
            class="lep-metric"
            :class="`tone-${metric.tone ?? 'default'}`"
          >
            <div class="lep-metric-label">{{ metric.label }}</div>
            <div class="lep-metric-value">{{ metric.value }}</div>
            <div v-if="metric.hint" class="lep-metric-hint">{{ metric.hint }}</div>
          </div>
        </div>
      </section>

      <section class="lep-group">
        <div class="lep-group-head">
          <span class="lep-group-title">补全字段</span>
          <span class="lep-group-note">按补到的行数倒序 —— 富化价值最直接的证据</span>
        </div>
        <el-table v-if="fields.length > 0" :data="fields" size="small" border>
          <el-table-column prop="label" label="字段" width="110" />
          <el-table-column prop="field" label="键名" min-width="140" />
          <el-table-column prop="count" label="补到行数" width="100" align="right" />
        </el-table>
        <div v-else class="lep-empty">（没有字段被补全）</div>
      </section>

      <section v-if="skips.length > 0" class="lep-group">
        <div class="lep-group-head">
          <span class="lep-group-title">L3 跳过原因</span>
          <span class="lep-group-note">回答「为什么这次没学到模板」</span>
        </div>
        <ul class="lep-list">
          <li v-for="row in skips" :key="row.key">
            <span class="lep-list-label">{{ row.label }}</span>
            <span class="lep-list-count">{{ row.count }} 次</span>
          </li>
        </ul>
      </section>

      <section v-if="domains.length > 0" class="lep-group">
        <div class="lep-group-head">
          <span class="lep-group-title">学过模板的域</span>
          <span class="lep-group-note">同域后续页面走模板，零 LLM 调用</span>
        </div>
        <div class="lep-tags">
          <el-tag v-for="domain in domains" :key="domain" size="small" type="success" effect="plain">
            {{ domain }}
          </el-tag>
        </div>
      </section>

      <section v-if="hasIssues" class="lep-group">
        <div class="lep-group-head">
          <span class="lep-group-title">需要留意</span>
        </div>

        <div v-if="conflicts.length > 0" class="lep-issue">
          <div class="lep-issue-head">
            表格值 vs 链接值冲突
            <span class="lep-list-count">{{ stats?.conflicts_count ?? conflicts.length }} 条</span>
          </div>
          <ul class="lep-list mono">
            <li v-for="(item, i) in preview(conflicts)" :key="i">{{ item }}</li>
          </ul>
          <div v-if="conflicts.length > PREVIEW_LIMIT" class="lep-more">
            其余 {{ conflicts.length - PREVIEW_LIMIT }} 条见 JSON 页签
          </div>
        </div>

        <div v-if="blocked.length > 0" class="lep-issue">
          <div class="lep-issue-head">
            被安全守卫拦下的地址
            <span class="lep-list-count">{{ blocked.length }} 个</span>
          </div>
          <ul class="lep-list mono">
            <li v-for="(item, i) in preview(blocked)" :key="i">{{ item }}</li>
          </ul>
          <div v-if="blocked.length > PREVIEW_LIMIT" class="lep-more">
            其余 {{ blocked.length - PREVIEW_LIMIT }} 条见 JSON 页签
          </div>
        </div>

        <div v-if="errors.length > 0" class="lep-issue">
          <div class="lep-issue-head">
            错误
            <span class="lep-list-count">{{ errors.length }} 条</span>
          </div>
          <ul class="lep-list mono">
            <li v-for="(item, i) in preview(errors)" :key="i">{{ item }}</li>
          </ul>
          <div v-if="errors.length > PREVIEW_LIMIT" class="lep-more">
            其余 {{ errors.length - PREVIEW_LIMIT }} 条见 JSON 页签
          </div>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.lep {
  margin-top: 12px;
}

.lep-banner {
  margin-bottom: 12px;
}

.lep-group {
  margin-bottom: 18px;
}

.lep-group-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #ebeef5;
}

.lep-group-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
}

.lep-group-note {
  font-size: 12px;
  color: #909399;
}

.lep-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}

.lep-metric {
  padding: 8px 10px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafcff;
}

.lep-metric-label {
  font-size: 12px;
  color: #909399;
}

.lep-metric-value {
  margin-top: 2px;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  word-break: break-all;
}

.lep-metric-hint {
  margin-top: 2px;
  font-size: 11px;
  line-height: 1.5;
  color: #a8abb2;
}

.lep-metric.tone-good {
  border-color: #d1edc4;
  background: #f6fdf4;
}

.lep-metric.tone-good .lep-metric-value {
  color: #529b2e;
}

.lep-metric.tone-warn {
  border-color: #f3d19e;
  background: #fdf8ef;
}

.lep-metric.tone-warn .lep-metric-value {
  color: #b88230;
}

.lep-list {
  margin: 0;
  padding-left: 0;
  list-style: none;
}

.lep-list li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 3px 0;
  font-size: 12px;
  color: #606266;
}

.lep-list.mono li {
  display: block;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  word-break: break-all;
}

.lep-list-label {
  color: #606266;
}

.lep-list-count {
  margin-left: 8px;
  color: #909399;
  white-space: nowrap;
}

.lep-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.lep-issue {
  margin-bottom: 10px;
}

.lep-issue-head {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: #b88230;
}

.lep-more {
  margin-top: 2px;
  font-size: 11px;
  color: #a8abb2;
}

.lep-empty {
  padding: 6px 0;
  font-size: 12px;
  color: #909399;
}
</style>
