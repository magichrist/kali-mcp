<script setup lang="ts">
</script>

<template>
  <section class="pagehead">
    <div class="page-top">
      <div id="pageHeadInfo"></div>
      <div class="head-right" id="pageHeadActions"></div>
    </div>
  </section>
  <section class="pagebody" id="pageBody">
    <slot />
  </section>
</template>

<style scoped>
.pagebody {
  min-height: 0;
  min-width: 0;
}
</style>
