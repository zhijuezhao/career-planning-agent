<script setup lang="ts">
/**
 * 报告正文渲染（Task 15，克制：不引入 markdown 依赖，手写解析）
 * 支持行级语法：`## 标题`、`### 标题`、`- 列表项`、`**加粗**`、`1. 有序项`、空行分段。
 * ⚠️ 与计划示例的差异（R-15.1）：示例把各类块 filter 后分组渲染，会**打乱正文顺序**；
 * 这里按原文档顺序单次渲染，标题/列表/段落穿插关系与 report_text 一致。
 */
import { computed } from 'vue'

interface Block {
  type: 'h2' | 'h3' | 'li' | 'oli' | 'p'
  text: string
}

const props = defineProps<{ text: string | null | undefined }>()

const blocks = computed<Block[]>(() => {
  const raw = props.text ?? ''
  const out: Block[] = []
  for (const line of raw.split('\n')) {
    const t = line.trim()
    if (!t) continue
    if (t.startsWith('### ')) out.push({ type: 'h3', text: t.slice(4) })
    else if (t.startsWith('## ')) out.push({ type: 'h2', text: t.slice(3) })
    else if (t.startsWith('# ')) out.push({ type: 'h2', text: t.slice(2) })
    else if (t.startsWith('- ') || t.startsWith('* ')) out.push({ type: 'li', text: t.slice(2) })
    else if (/^\d+[.、]\s*/.test(t)) out.push({ type: 'oli', text: t.replace(/^\d+[.、]\s*/, '') })
    else out.push({ type: 'p', text: t })
  }
  return out
})

/** 行内 **加粗** → 分段渲染（返回纯文本段与加粗段交替） */
function segments(text: string): { bold: boolean; text: string }[] {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return parts
    .map((part, i) => ({ bold: i % 2 === 1, text: part }))
    .filter(seg => seg.text !== '')
}
</script>

<template>
  <div class="report-markdown">
    <p v-if="!blocks.length" class="md-empty">（报告正文为空）</p>
    <template v-for="(b, i) in blocks" :key="`${b.type}-${i}`">
      <h2 v-if="b.type === 'h2'" class="md-h2">
        <template v-for="(s, si) in segments(b.text)" :key="si">
          <strong v-if="s.bold">{{ s.text }}</strong><span v-else>{{ s.text }}</span>
        </template>
      </h2>
      <h3 v-else-if="b.type === 'h3'" class="md-h3">
        <template v-for="(s, si) in segments(b.text)" :key="si">
          <strong v-if="s.bold">{{ s.text }}</strong><span v-else>{{ s.text }}</span>
        </template>
      </h3>
      <ul v-else-if="b.type === 'li'" class="md-ul">
        <li>
          <template v-for="(s, si) in segments(b.text)" :key="si">
            <strong v-if="s.bold">{{ s.text }}</strong><span v-else>{{ s.text }}</span>
          </template>
        </li>
      </ul>
      <ol v-else-if="b.type === 'oli'" class="md-ol">
        <li>
          <template v-for="(s, si) in segments(b.text)" :key="si">
            <strong v-if="s.bold">{{ s.text }}</strong><span v-else>{{ s.text }}</span>
          </template>
        </li>
      </ol>
      <p v-else class="md-p">
        <template v-for="(s, si) in segments(b.text)" :key="si">
          <strong v-if="s.bold">{{ s.text }}</strong><span v-else>{{ s.text }}</span>
        </template>
      </p>
    </template>
  </div>
</template>

<style scoped>
.report-markdown {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  font-size: var(--text-base);
  line-height: 1.9;
  color: var(--c-text-2);
}
.md-empty {
  margin: 0;
  color: var(--c-text-3);
  font-size: var(--text-sm);
}
.md-h2 {
  margin: var(--space-4) 0 0;
  font-size: 18px;
  font-weight: 700;
  color: var(--c-text-1);
  padding-bottom: var(--space-2);
  border-bottom: 1px solid var(--c-bg-mute);
}
.md-h3 {
  margin: var(--space-3) 0 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--c-text-1);
}
.md-p {
  margin: 0;
  word-break: break-word;
}
.md-ul,
.md-ol {
  margin: 0;
  padding-left: var(--space-5);
}
.md-ul li,
.md-ol li {
  margin: 0 0 var(--space-1);
}
.report-markdown strong {
  color: var(--c-text-1);
}
</style>
