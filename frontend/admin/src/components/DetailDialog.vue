<script lang="ts">
/**
 * 详情卡标签类型（导出给各页复用）。
 * `<script setup>` 内不允许出现 ES 导出语句，因此类型单开一个普通 script 块。
 */
export type DetailTagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export interface DetailTag {
  text: string
  type?: DetailTagType
}
</script>

<script setup lang="ts">
/**
 * 详情预览卡（P1-1，需求 8）
 *
 * 对齐 Coze 的弹窗卡片结构：头部（标题 + 标签 + 副标题）→ Tabs（预览 / JSON）
 * → 可滚动内容区 → 底部（复制 Markdown / 复制 JSON / 关闭）。
 *
 * 约定：**管理端所有「详情」一律用它**，各页不要再自己写 `el-dialog` 详情，
 * 以保证交互与视觉一致（改动只发生在这一处）。
 */
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownPreview from './MarkdownPreview.vue'

const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    subtitle?: string
    tags?: DetailTag[]
    markdown?: string | null
    /** 传了才出现 JSON 页签（`undefined`/`null` 视为无） */
    json?: unknown
    width?: string
    maxHeight?: string
    jsonLabel?: string
    /** JSON 页签默认文案 */
    emptyText?: string
  }>(),
  {
    title: '详情',
    subtitle: '',
    tags: () => [],
    markdown: '',
    json: undefined,
    width: '720px',
    maxHeight: '60vh',
    jsonLabel: 'JSON',
    emptyText: '（暂无内容）',
  },
)

const emit = defineEmits<{ 'update:modelValue': [value: boolean] }>()

const activeTab = ref<'preview' | 'json'>('preview')

const hasJson = computed(() => props.json !== undefined && props.json !== null)

const jsonText = computed(() => {
  if (!hasJson.value) return ''
  try {
    return JSON.stringify(props.json, null, 2)
  } catch {
    return String(props.json)
  }
})

/** 每次打开都回到「预览」页签，避免上次停在 JSON 造成困惑 */
watch(
  () => props.modelValue,
  (open) => {
    if (open) activeTab.value = 'preview'
  },
)

function close() {
  emit('update:modelValue', false)
}

async function copy(text: string, label: string) {
  if (!text) {
    ElMessage.warning('没有可复制的内容')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success(`${label}已复制`)
  } catch {
    ElMessage.warning('复制失败（浏览器限制），请手动选择文本复制')
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :width="width"
    append-to-body
    destroy-on-close
    class="detail-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="dd-header">
        <div class="dd-title-row">
          <span class="dd-title">{{ title }}</span>
          <el-tag
            v-for="tag in tags"
            :key="tag.text"
            :type="tag.type || 'info'"
            size="small"
            effect="light"
          >
            {{ tag.text }}
          </el-tag>
        </div>
        <div v-if="subtitle" class="dd-subtitle">{{ subtitle }}</div>
      </div>
    </template>

    <el-tabs v-model="activeTab" class="dd-tabs">
      <el-tab-pane label="预览" name="preview">
        <div class="dd-body" :style="{ maxHeight }">
          <MarkdownPreview :text="markdown" :empty-text="emptyText" />
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="hasJson" :label="jsonLabel" name="json">
        <div class="dd-body" :style="{ maxHeight }">
          <pre class="dd-json">{{ jsonText }}</pre>
        </div>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <div class="dd-footer">
        <el-button size="small" @click="copy(markdown || '', 'Markdown')">复制 Markdown</el-button>
        <el-button v-if="hasJson" size="small" @click="copy(jsonText, 'JSON')">复制 JSON</el-button>
        <el-button type="primary" size="small" @click="close">关闭</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.dd-header {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 24px;
}

.dd-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dd-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.dd-subtitle {
  font-size: 12px;
  color: #909399;
  word-break: break-all;
}

.dd-tabs {
  margin-top: -6px;
}

.dd-body {
  overflow: auto;
  padding: 4px 2px;
}

.dd-json {
  margin: 0;
  padding: 10px 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  font-family: 'JetBrains Mono', Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-word;
}

.dd-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
