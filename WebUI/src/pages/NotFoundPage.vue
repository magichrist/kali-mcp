<script setup lang="ts">
import { useRoute } from "vue-router";
</script>

<template>
  <div class="page-container">
    <div class="page-head">
      <div class="eyebrow">NOT FOUND</div>
      <h1>Page not found</h1>
      <p class="subtitle">No page matches route <code>{{ route.path }}</code>.</p>
    </div>
    <div class="empty" style="padding:40px">The requested studio page does not exist. Use the sidebar navigation to browse available pages.</div>
  </div>
</template>

<style scoped>
.page-container { padding: 26px 32px 32px; max-width: 1720px; margin: 0 auto; width: 100%; }
.page-head { margin-bottom: 16px; }
.page-head .eyebrow { margin-bottom: 6px; }
</style>
