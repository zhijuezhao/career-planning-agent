<script setup lang="ts">
import { useRoute } from 'vue-router'

const name = useRoute().name
if (name === 'Home') window.location.replace('/dashboard')
if (name === 'Chat') window.location.replace('/chat')
</script>

<template>
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--c-text-3)">
    跳转中…
  </div>
</template>