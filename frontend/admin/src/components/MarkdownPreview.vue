<script setup lang="ts">
/**
 * Markdown 预览（P1-1）
 *
 * 取舍：**不引入 markdown 依赖**，沿用学生端 `ReportMarkdown.vue` 的自研极简解析；
 * 只产出文本节点（`<span>/<strong>/<code>`），**从不 v-html**，因此天然无 XSS 面。
 *
 * 解析逻辑在 `@/utils/preview`（纯函数，可单测）；本组件只负责把块结构渲染成模板。
 * 为避免模板里做联合类型收窄，这里把块归一成「字段全部可选」的渲染结构。
 */
import { computed } from 'vue'
import { inlineSegments, parseMarkdown } from '@/utils/preview'

interface RenderItem {
  text: string
  depth: number
}

interface RenderBlock {
  kind: 'heading' | 'paragraph' | 'quote' | 'list' | 'code'
  level: 1 | 2 | 3
  text: string
  lang: string
  ordered: boolean
  items: RenderItem[]
}

interface RenderSegment {
  text: string
  bold: boolean
  code: boolean
}

const props = withDefaults(
  defineProps<{
    text?: string | null
    emptyText?: string
  }>(),
  {
    text: '',
    emptyText: '（暂无内容）',
  },
)

const blocks = computed<RenderBlock[]>(() =>
  parseMarkdown(props.text).map((block) => ({
    kind: block.kind,
    level: block.kind === 'heading' ? block.level : 1,
    text: 'text' in block ? block.text : '',
    lang: block.kind === 'code' ? block.lang : '',
    ordered: block.kind === 'list' ? block.ordered : false,
    items: block.kind === 'list' ? block.items : [],
  })),
)

function segments(text: string): RenderSegment[] {
  return inlineSegments(text).map((seg) => ({
    text: seg.text,
    bold: seg.type === 'bold',
    code: seg.type === 'code',
  }))
}
</script>

<template>
  <div class="markdown-preview">
    <p v-if="!blocks.length" class="md-empty">{{ emptyText }}</p>

    <template v-for="(block, index) in blocks" :key="index">
      <h3 v-if="block.kind === 'heading' && block.level === 3" class="md-heading md-h3">
        <template v-for="(seg, si) in segments(block.text)" :key="si">
          <strong v-if="seg.bold">{{ seg.text }}</strong>
          <code v-else-if="seg.code" class="md-inline-code">{{ seg.text }}</code>
          <span v-else>{{ seg.text }}</span>
        </template>
      </h3>

      <h2 v-else-if="block.kind === 'heading' && block.level === 2" class="md-heading md-h2">
        <template v-for="(seg, si) in segments(block.text)" :key="si">
          <strong v-if="seg.bold">{{ seg.text }}</strong>
          <code v-else-if="seg.code" class="md-inline-code">{{ seg.text }}</code>
          <span v-else>{{ seg.text }}</span>
        </template>
      </h2>

      <h1 v-else-if="block.kind === 'heading'" class="md-heading md-h1">
        <template v-for="(seg, si) in segments(block.text)" :key="si">
          <strong v-if="seg.bold">{{ seg.text }}</strong>
          <code v-else-if="seg.code" class="md-inline-code">{{ seg.text }}</code>
          <span v-else>{{ seg.text }}</span>
        </template>
      </h1>

      <pre v-else-if="block.kind === 'code'" class="md-code-block"><code>{{ block.text }}</code></pre>

      <blockquote v-else-if="block.kind === 'quote'" class="md-quote">
        <template v-for="(seg, si) in segments(block.text)" :key="si">
          <strong v-if="seg.bold">{{ seg.text }}</strong>
          <code v-else-if="seg.code" class="md-inline-code">{{ seg.text }}</code>
          <span v-else>{{ seg.text }}</span>
        </template>
      </blockquote>

      <ol v-else-if="block.kind === 'list' && block.ordered" class="md-list">
        <li
          v-for="(item, ii) in block.items"
          :key="ii"
          :style="{ marginLeft: `${item.depth * 14}px` }"
        >
          <template v-for="(seg, si) in segments(item.text)" :key="si">
            <strong v-if="seg.bold">{{ seg.text }}</strong>
            <code v-else-if="seg.code" class="md-inline-code">{{ seg.text }}</code>
            <span v-else>{{ seg.text }}</span>
          </template>
        </li>
      </ol>

      <ul v-else-if="block.kind === 'list'" class="md-list">
        <li
          v-for="(item, ii) in block.items"
          :key="ii"
          :style="{ marginLeft: `${item.depth * 14}px` }"
        >
          <template v-for="(seg, si) in segments(item.text)" :key="si">
            <strong v-if="seg.bold">{{ seg.text }}</strong>
            <code v-else-if="seg.code" class="md-inline-code">{{ seg.text }}</code>
            <span v-else>{{ seg.text }}</span>
          </template>
        </li>
      </ul>

      <p v-else class="md-paragraph">
        <template v-for="(seg, si) in segments(block.text)" :key="si">
          <strong v-if="seg.bold">{{ seg.text }}</strong>
          <code v-else-if="seg.code" class="md-inline-code">{{ seg.text }}</code>
          <span v-else>{{ seg.text }}</span>
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
.markdown-preview {
  font-size: 13px;
  line-height: 1.85;
  color: #606266;
  word-break: break-word;
}

.md-empty {
  margin: 0;
  color: #909399;
}

.md-heading {
  margin: 14px 0 6px;
  color: #303133;
  line-height: 1.5;
}

.md-h1 {
  font-size: 17px;
  font-weight: 700;
  padding-bottom: 6px;
  border-bottom: 1px solid #ebeef5;
}

.md-h2 {
  font-size: 15px;
  font-weight: 600;
}

.md-h3 {
  font-size: 14px;
  font-weight: 600;
}

.md-paragraph {
  margin: 6px 0;
}

.md-list {
  margin: 6px 0;
  padding-left: 20px;
}

.md-list li {
  margin: 3px 0;
}

.md-quote {
  margin: 6px 0;
  padding: 2px 0 2px 10px;
  border-left: 3px solid #dcdfe6;
  color: #909399;
}

.md-code-block {
  margin: 8px 0;
  padding: 10px 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow-x: auto;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
}

.md-inline-code {
  padding: 1px 5px;
  background: #f5f7fa;
  border-radius: 4px;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 12px;
  color: #c7254e;
}

.markdown-preview strong {
  color: #303133;
  font-weight: 600;
}
</style>
