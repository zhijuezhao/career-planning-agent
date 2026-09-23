<script setup lang="ts">
/**
 * 快照管理（P1-1 占位页）
 *
 * P1-4 会把它替换成完整页面：列表（用户ID/用户名/生成时间/匹配状态/六维摘要）
 * + 详情预览卡 + 下载（Markdown）/ 修改（备注与五层画像）/ 删除。
 * 这里先占住导航入口，避免导航缺失造成「功能不存在」的错觉。
 */
</script>

<template>
  <el-card class="data-card">
    <el-empty description="快照管理建设中（P1-4 交付）" />
  </el-card>
</template>

<style scoped>
.data-card {
  border-radius: 12px;
  border: 1px solid #e6e6e6;
}
</style>
