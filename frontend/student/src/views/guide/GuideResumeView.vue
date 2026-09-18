<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import { profileApi, type UploadParseResult } from '@/api/profile'
import { useJourneyStore } from '@/stores/journey'

/** 解析结果透传 key：/guide/parse 读取同一份 sessionStorage 数据 */
const PARSE_RESULT_KEY = 'guide.parse_result'

const router = useRouter()
const journey = useJourneyStore()

const uploading = ref(false)

/** 后端仅接受 PDF（扩展名 + %PDF magic + 体积上限均由后端校验） */
function isPdfFile(name: string): boolean {
  return name.toLowerCase().endsWith('.pdf')
}

function cacheParseResult(res: UploadParseResult): void {
  try {
    sessionStorage.setItem(PARSE_RESULT_KEY, JSON.stringify(res))
  } catch {
    // 隐私模式 / 配额不足：缓存失败不阻塞后续流程
  }
}

async function onFile(file: { raw: File }): Promise<void> {
  if (!file?.raw) return
  if (!isPdfFile(file.raw.name)) {
    ElMessage.error('仅支持 PDF 格式')
    return
  }
  uploading.value = true
  try {
    const res = await profileApi.uploadResumeForParse(file.raw)
    cacheParseResult(res)
    try {
      await journey.fetchStatus()
    } catch {
      // 旅程状态刷新失败（离线等）不阻塞跳转
    }
    ElMessage.success('解析完成，请核对画像')
    router.push('/guide/parse')
  } catch (e: any) {
    const detail = e?.response?.data?.detail
    ElMessage.error(detail || '解析失败，请重试')
  } finally {
    uploading.value = false
  }
}
</script>

<template>
  <div class="guide-page">
    <h2 class="guide-title">上传简历</h2>
    <p class="guide-desc">
      上传你的 PDF 简历，AI 会解析出五层能力画像与六维评分，作为后续岗位匹配与成长策略的依据。
    </p>

    <div v-loading="uploading" class="upload-wrap">
      <el-upload
        class="upload-zone"
        drag
        accept=".pdf"
        :auto-upload="false"
        :show-file-list="false"
        :on-change="onFile"
        :disabled="uploading"
      >
        <el-icon class="upload-icon" :size="48"><UploadFilled /></el-icon>
        <div class="upload-text">拖拽 PDF 简历到此处，或点击选择文件</div>
        <div class="upload-hint">仅支持 PDF 格式（.pdf），最大 10MB</div>
      </el-upload>
    </div>

    <p v-if="uploading" class="parse-hint">正在解析，约需 10-30 秒…</p>
    <p v-else class="parse-hint is-idle">解析完成后会自动进入下一步，请勿关闭页面。</p>

    <p class="uploaded-hint">
      已上传过？
      <router-link to="/guide/parse">直接查看我的画像</router-link>
    </p>
  </div>
</template>

<style scoped>
.guide-page {
  max-width: 720px;
  margin: 0 auto;
}

.guide-title {
  font-family: var(--font-display);
  font-size: 28px;
  font-weight: 600;
  color: var(--c-text-1);
  margin-bottom: var(--space-3);
}

.guide-desc {
  font-size: var(--text-base);
  line-height: 1.7;
  color: var(--c-text-2);
}

.upload-wrap {
  position: relative;
  margin-top: var(--space-8);
}

.upload-zone :deep(.el-upload) {
  width: 100%;
}

.upload-zone :deep(.el-upload-dragger) {
  padding: var(--space-12) var(--space-6);
  border: 2px dashed var(--c-bg-mute);
  border-radius: var(--radius-lg);
  background: var(--c-surface);
  box-shadow: var(--shadow-xs);
  transition: border-color 150ms ease, background-color 150ms ease;
}

.upload-zone :deep(.el-upload-dragger:hover) {
  border-color: var(--c-brand);
  background: var(--c-brand-lighter);
}

.upload-zone :deep(.el-upload-dragger.is-disabled) {
  background: var(--c-bg-soft);
  cursor: not-allowed;
}

.upload-icon {
  color: var(--c-brand);
}

.upload-text {
  margin-top: var(--space-4);
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--c-text-1);
}

.upload-hint {
  margin-top: var(--space-2);
  font-size: var(--text-sm);
  color: var(--c-text-3);
}

.parse-hint {
  margin-top: var(--space-4);
  font-size: var(--text-sm);
  color: var(--c-brand);
}

.parse-hint.is-idle {
  color: var(--c-text-3);
}

.uploaded-hint {
  margin-top: var(--space-6);
  font-size: var(--text-sm);
  color: var(--c-text-3);
}

.uploaded-hint a {
  color: var(--c-brand);
  text-decoration: none;
}

.uploaded-hint a:hover {
  text-decoration: underline;
}
</style>
