<template>
  <div class="modal-backdrop" v-if="show" @click.self="close">
    <div class="modal run-modal">
      <div class="modal-head">
        <h3>Run “{{ playbookId }}”</h3>
        <p class="dim">Runs the published version. Provide input values below; anything omitted falls back to its default.</p>
      </div>
      <div class="modal-body">
        <div v-if="!specs.length" class="empty">No declared inputs — start the run directly, or add extra ones as JSON below.</div>
        <div v-else>
          <div class="run-row" v-for="spec in specs" :key="spec.name">
            <div class="run-row-head">
              <b class="mono">{{ spec.name }}</b>
              <span class="chip" :class="{ ck: spec.spec.required }">{{ spec.spec.type }} · {{ spec.spec.required ? "required" : "optional" }}</span>
              <span v-if="spec.referenced" class="chip" style="font-size:10px;padding:0 5px;color:var(--cyan)">referenced</span>
            </div>
            <div class="run-field" :class="`run-field--${spec.spec.type}`">
              <input v-if="isText(spec)" v-model="values[spec.name]" :placeholder="defaultPlaceholder(spec)" class="input" />
              <select v-else-if="isBoolean(spec)" v-model="boolValues[spec.name]" class="input">
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
              <input v-else-if="isNumber(spec)" type="number" v-model.number="numValues[spec.name]" class="input" />
              <textarea v-else v-model="jsonValues[spec.name]" class="area" :placeholder="defaultPlaceholder(spec)" />
            </div>
          </div>
          <div class="run-row">
            <div class="run-row-head"><b>Placeholders used in this playbook</b> <span class="chip">{{ refNames.length }} referenced</span></div>
            <p class="dim ins-note">{{ refNames.join(", ") || "none" }} — these {{name}} references appear in step inputs, args, or commands.</p>
          </div>
          <div class="run-row">
            <div class="run-row-head"><b>Extra inputs</b> <span class="chip">JSON · optional</span></div>
            <textarea v-model="extraJson" class="area" spellcheck="false" placeholder="{}" />
          </div>
          <div class="run-row">
            <label class="checkline" style="margin:0">
              <input type="checkbox" v-model="debug" /> Debug run (marks this execution as a manual debug run)
            </label>
          </div>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn" @click="close">Cancel</button>
        <button class="btn primary" @click="start" :disabled="busy">▶ Start run</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { gatherRunSpecs } from "@/features/playbook-editor/composables/useRunInputs";
import { useNotifications } from "@/stores/notifications";

const props = defineProps<{
  show: boolean;
  playbookId: string | null;
  definition: any;
}>();

const emit = defineEmits<{ (e: "update:show", show: boolean): void; (e: "run-start", payload: { inputs: Record<string, unknown>; debug: boolean }): void }>();

const notify = useNotifications();
const busy = ref(false);
const debug = ref(true);
const extraJson = ref("{}");

const values: Record<string, unknown> = reactive({});
const boolValues: Record<string, string> = reactive({});
const numValues: Record<string, number> = reactive({});
const jsonValues: Record<string, string> = reactive({});

let resolvedSpecs: any[] = [];

watch(
  () => props.definition,
  (def) => {
    resolvedSpecs = def ? gatherRunSpecs(def) : [];
    for (const s of resolvedSpecs) {
      const deflt = s.spec.default;
      if (deflt !== undefined) {
        values[s.name] = deflt;
        if (s.spec.type === "boolean") boolValues[s.name] = String(deflt);
        else if (s.spec.type === "number") numValues[s.name] = Number(deflt) || 0;
        else if (s.spec.type === "object" || s.spec.type === "array") jsonValues[s.name] = JSON.stringify(deflt);
        else values[s.name] = String(deflt);
      } else {
        values[s.name] = "";
        if (s.spec.type === "boolean") boolValues[s.name] = "false";
        else if (s.spec.type === "number") numValues[s.name] = 0;
        else if (s.spec.type === "object" || s.spec.type === "array") jsonValues[s.name] = s.spec.type === "array" ? "[]" : "{}";
        else values[s.name] = "";
      }
    }
  },
  { immediate: true },
);

const specs = computed(() => resolvedSpecs);
const refNames = computed(() => resolvedSpecs.filter((s) => s.referenced).map((s) => s.name));

function isText(s: any) { return s.spec.type === "string" || s.spec.type === "secret" || s.spec.type === "scope_reference" || !(["boolean","number","object","array"] as string[]).includes(s.spec.type); }
function isBoolean(s: any) { return s.spec.type === "boolean"; }
function isNumber(s: any) { return s.spec.type === "integer" || s.spec.type === "number"; }
function defaultPlaceholder(s: any) { return s.spec.type === "array" ? "[]" : s.spec.type === "object" ? "{}" : ""; }

function close() { emit("update:show", false); }

async function start() {
  const inputs: Record<string, unknown> = { ...values };
  let ok = true;
  for (const s of resolvedSpecs) {
    let v = inputs[s.name];
    if (s.spec.type === "boolean") v = boolValues[s.name] === "true";
    else if (s.spec.type === "number") v = numValues[s.name];
    else if (s.spec.type === "object" || s.spec.type === "array") {
      const raw = jsonValues[s.name] ?? "";
      if (!raw.trim()) { delete inputs[s.name]; continue; }
      try { v = JSON.parse(raw); } catch { notify.toast(`Input ${s.name} must be valid JSON`, "error"); ok = false; continue; }
    } else {
      v = values[s.name] ?? "";
      if (v === "") { delete inputs[s.name]; continue; }
    }
    if (v !== undefined) inputs[s.name] = v;
  }
  let extra: Record<string, unknown> = {};
  const raw = extraJson.value.trim();
  if (raw) {
    try { extra = JSON.parse(raw); } catch { notify.toast("Extra inputs must be valid JSON", "error"); ok = false; }
  }
  if (!ok) return;
  Object.assign(inputs, extra);
  busy.value = true;
  try {
    emit("run-start", { inputs, debug: debug.value === true });
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.modal-backdrop { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.55); z-index: 50; }
.modal { background: #1e1e1e; border: 1px solid #3a3a3a; border-radius: var(--radius); width: min(560px, 92vw); max-height: 85vh; overflow: auto; box-shadow: var(--shadow); }
.modal-head { padding: 16px 18px 8px; border-bottom: 1px solid #2a2a2a; }
.modal-head h3 { margin: 0 0 6px; font-size: 17px; color: var(--text); }
.modal-body { padding: 14px 18px; display: flex; flex-direction: column; gap: 12px; }
.run-row { display: flex; flex-direction: column; gap: 6px; }
.run-row-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.run-row-head b { font-size: 13px; color: var(--text); }
.run-field { display: flex; flex-direction: column; gap: 4px; }
.area { font-family: ui-monospace, Menlo, monospace; font-size: 12px; min-height: 96px; }
.checkline { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); cursor: pointer; }
.checkline input { width: 16px; height: 16px; accent-color: var(--green-strong); flex: none; }
.modal-actions { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 18px; border-top: 1px solid #2a2a2a; }
.empty { color: var(--dim); font-size: 12.5px; }
.ins-note { font-size: 11.5px; color: var(--dim); margin: 4px 0 0; }
</style>
