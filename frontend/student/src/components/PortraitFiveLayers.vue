<script setup lang="ts">
/**
 * 五层能力画像展示（共享组件，Task 14）
 * 输入五层原始 JSON（shape 不可知），递归做防御性格式化后按层渲染。
 * 数据来源可为：/resume/upload 返回的 five_layers、/profile/snapshots/{id} 的 five_layers。
 */
import { computed } from 'vue'

interface LayerItem {
  key: string
  text: string
}

interface LayerCard {
  key: string
  label: string
  hint: string
  items: LayerItem[]
}

const props = defineProps<{
  fiveLayers: Record<string, any> | null | undefined
  /** 紧凑模式：减小卡片内边距（业务区侧栏/摘要场景用） */
  compact?: boolean
}>()

const LAYER_META: { key: string; label: string; hint: string }[] = [
  { key: 'intention', label: '意向层', hint: '目标行业 / 岗位 / 城市 / 薪资' },
  { key: 'traits', label: '特质层', hint: '性格标签 / 擅长方向 / 价值观' },
  { key: 'practice', label: '实践层', hint: '实习 / 项目 / 竞赛 / 校园经历' },
  { key: 'soft_skills', label: '软技能层', hint: '沟通 / 协作 / 抗压 / 学习' },
  { key: 'hard_skills', label: '硬技能层', hint: '专业技能 / 学历 / 证书' },
]

function formatScalar(value: unknown): string {
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function formatValue(value: unknown): string {
  if (value == null) return ''
  const scalar = formatScalar(value)
  if (scalar) return scalar
  if (Array.isArray(value)) {
    return value.map(item => formatValue(item)).filter(Boolean).join('、')
  }
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => {
        const text = formatValue(item)
        return text ? `${key}：${text}` : ''
      })
      .filter(Boolean)
      .join('；')
  }
  return ''
}

function toItems(value: unknown): LayerItem[] {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) {
    const text = formatValue(value)
    return text ? [{ key: '', text }] : []
  }
  return Object.entries(value as Record<string, unknown>)
    .map(([key, item]) => ({ key, text: formatValue(item) }))
    .filter(item => item.text !== '')
}

const layerCards = computed<LayerCard[]>(() => {
  const source = props.fiveLayers ?? null
  return LAYER_META.map(meta => ({
    key: meta.key,
    label: meta.label,
    hint: meta.hint,
    items: toItems(source ? source[meta.key] : null),
  }))
})

/** 是否至少有一层有内容 */
const hasAny = computed(() => layerCards.value.some(layer => layer.items.length > 0))
</script>

<template>
  <div class="portrait-layers" :class="{ compact }">
    <p v-if="!hasAny" class="layers-empty">暂无画像内容</p>
    <section v-for="layer in layerCards" v-else :key="layer.key" class="layer-card">
      <div class="layer-head">
        <h3 class="layer-title">{{ layer.label }}</h3>
        <span class="layer-hint">{{ layer.hint }}</span>
      </div>
      <div v-if="layer.items.length" class="layer-body">
        <p v-for="item in layer.items" :key="item.key || item.text" class="layer-item">
          <span v-if="item.key" class="item-key">{{ item.key }}</span>
          <span class="item-text">{{ item.text }}</span>
        </p>
      </div>
      <p v-else class="layer-empty">暂无</p>
    </section>
  </div>
</template>

<style scoped>
.portrait-layers {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}
.layers-empty {
  margin: 0;
  padding: var(--space-6);
  text-align: center;
  font-size: var(--text-sm);
  color: var(--c-text-3);
}
.layer-card {
  padding: var(--space-4) var(--space-5);
  background: var(--c-surface);
  border: 1px solid var(--c-bg-mute);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
}
.compact .layer-card {
  padding: var(--space-3) var(--space-4);
}
.layer-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}
.layer-title {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--c-text-1);
}
.layer-hint {
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
.layer-body {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}
.layer-item {
  display: flex;
  gap: var(--space-2);
  margin: 0;
  font-size: var(--text-sm);
  line-height: 1.7;
  color: var(--c-text-2);
}
.item-key {
  flex: none;
  min-width: 72px;
  color: var(--c-text-3);
}
.item-text {
  flex: 1;
  min-width: 0;
  word-break: break-word;
}
.layer-empty {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--c-text-3);
}
</style>
