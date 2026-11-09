<script setup lang="ts">
import BaseNode from "./BaseNode.vue";
const props = defineProps<{ id: string; data: { step: any; __status?: string }; selected?: boolean }>();
const step = props.data.step;
const argCount = step?.args ? Object.keys(step.args).length : 0;

</script>

<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="node-body"><div class="shell-line"><i>tool</i><b>{{ step.tool || "—" }}</b><span v-if="argCount"> · {{ argCount }} arg(s)</span><span v-else class="dim">no arguments</span></div><div v-if="step.when" class="shell-line"><i>when</i><span>{{ step.when }}</span></div></div>
  </BaseNode>
</template>
