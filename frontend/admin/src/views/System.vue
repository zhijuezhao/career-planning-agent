<script setup lang="ts">
/**
 * 系统配置（B2-1 重构）
 *
 * 四块 + 一块只读留档：
 *   ① 供应商：OpenAI 兼容地址 + 加密密钥（回显掩码）
 *   ② 模型：挂在供应商下，区分 chat / embedding
 *   ③ 功能路由：功能键 → 模型（**保存即生效，无需重启**）
 *   ④ 调度器：原样保留
 *   ⑤ 旧版 AI 配置：只读留档（不参与生效）
 *
 * 切到某个 tab 时把 `reloadToken` +1，各面板 watch 到后重新拉取 —— 保证跨面板
 * 看到的是同一时刻的数据（例如刚删掉供应商，模型/路由 tab 不会显示幽灵数据）。
 */
import { ref } from 'vue'
import LegacyConfigsPanel from './system/LegacyConfigsPanel.vue'
import ModelsPanel from './system/ModelsPanel.vue'
import ProvidersPanel from './system/ProvidersPanel.vue'
import RoutesPanel from './system/RoutesPanel.vue'
import SchedulerPanel from './system/SchedulerPanel.vue'

const activeTab = ref('providers')
const reloadToken = ref(0)

const onTabChange = () => {
  reloadToken.value += 1
}
</script>

<template>
  <div>
    <el-tabs v-model="activeTab" class="system-tabs" @tab-change="onTabChange">
      <el-tab-pane label="供应商" name="providers">
        <ProvidersPanel :reload-token="reloadToken" />
      </el-tab-pane>
      <el-tab-pane label="模型" name="models">
        <ModelsPanel :reload-token="reloadToken" />
      </el-tab-pane>
      <el-tab-pane label="功能路由" name="routes">
        <RoutesPanel :reload-token="reloadToken" />
      </el-tab-pane>
      <el-tab-pane label="调度器" name="scheduler">
        <SchedulerPanel :reload-token="reloadToken" />
      </el-tab-pane>
      <el-tab-pane label="旧版配置（只读）" name="legacy">
        <LegacyConfigsPanel :reload-token="reloadToken" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.system-tabs {
  padding: 0 4px;
}
</style>
