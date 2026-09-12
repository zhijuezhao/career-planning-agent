<script setup lang="ts">
defineProps<{
  title: string
}>()
</script>

<template>
  <el-card>
    <template #header>
      <span>{{ title }}</span>
    </template>
    <el-empty description="功能开发中..." />
  </el-card>
</template>
