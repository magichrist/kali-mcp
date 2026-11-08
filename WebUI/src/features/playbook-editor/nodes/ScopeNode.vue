<script setup lang="ts">
import BaseNode from "./BaseNode.vue";
const props = defineProps<{ id: string; data: { step: any; __status?: string }; selected?: boolean }>();
const step = props.data.step;


</script>

<template>
  <BaseNode :id="id" :data="data" :selected="selected" v-slot="{ type }">
    <div class="node-body"><div class="shell-line"><i>scope</i><span>{{ step.scope || "scope check" }}</span></div><div class="shell-line"><i>when</i><span v-if="step.when">{{ step.when }}</span><span v-else class="dim">always</span></div></div>
  </BaseNode>
</template>
