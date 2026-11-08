<script setup lang="ts">
import { computed } from "vue";
import type { CSSProperties } from "vue";

const props = defineProps<{
  columns: Array<{ key: string; label: string }>;
  items: unknown[];
  rowRenderer?: (item: unknown) => { cells: Array<string | { html: string }>; menu?: string };
  emptyText?: string;
  class?: string;
  style?: CSSProperties;
}>();

type Cell = string | { html: string };

const computedColumns = computed(() => props.columns.length.map(() => "minmax(0,1fr)"));

const computedRows = computed(() => {
  if (!props.rowRenderer || !props.items.length) {
    return props.items.map((item) => ({
      cells: props.columns.map((col) => String((item as Record<string, unknown>)[col.key] ?? "—")),
      menu: "",
    }));
  }
  return props.items.map((item) => props.rowRenderer!(item));
});

function renderCell(cell: Cell): string {
  if (typeof cell === "object" && cell !== null && "html" in cell) {
    return cell.html;
  }
  return String(cell);
}
</script>

<template>
  <div class="panel table-panel" :class="class" :style="style">
    <div v-if="computedRows.length === 0" class="empty">
      {{ emptyText || "Nothing here yet." }}
    </div>
    <div v-else>
      <div class="table-head" :style="{ 'grid-template-columns': `${computedColumns.join(" ")} auto` }">
        <span v-for="col in props.columns" :key="col.key">{{ col.label }}</span>
        <span></span>
      </div>
      <div
        v-for="(row, i) in computedRows"
        :key="i"
        class="table-row"
        :style="{ 'grid-template-columns': `${computedColumns.join(" ")} auto` }"
      >
        <span v-for="(cell, ci) in row.cells" :key="ci">
          {{ renderCell(cell) }}
        </span>
        <span v-if="row.menu" v-html="row.menu" />
      </div>
    </div>
  </div>
</template>

<style scoped>
.table-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
