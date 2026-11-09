<script setup lang="ts">
import BaseNode from "./BaseNode.vue";
const props = defineProps<{ id: string; data: { step: any; __status?: string }; selected?: boolean }>();
const step = props.data.step;


</script>

<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="node-body"><div class="shell-line"><i>module</i><span>{{ step.module || step.tool || "custom stage" }}</span></div><div class="shell-line"><i>when</i><span v-if="step.when">{{ step.when }}</span><span v-else class="dim">always</span></div></div>
  </BaseNode>
</template>
