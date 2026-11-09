<script setup lang="ts">
import BaseNode from "./BaseNode.vue";
const props = defineProps<{ id: string; data: { step: any; __status?: string }; selected?: boolean }>();
const step = props.data.step;

const inputCount = step?.inputs ? Object.keys(step.inputs).length : 0; const hasFilter = step?.filter && step.filter.type !== "none";
</script>

<template>
  <BaseNode :id="id" :data="data" :selected="selected">
    <div class="node-body"><div class="shell-line"><i>in</i><span v-if="inputCount">{{ inputCount }} mapped input(s)</span><span v-else class="dim">no inputs</span></div><div class="shell-line cmd"><i>❯</i><span class="cmd-txt">{{ step.command || "no command" }}</span></div><div class="shell-line flt"><i>⌕</i><span v-if="hasFilter">{{ step.filter?.type || "grep" }}</span><span v-else class="dim">no filter</span></div></div>
  </BaseNode>
</template>
