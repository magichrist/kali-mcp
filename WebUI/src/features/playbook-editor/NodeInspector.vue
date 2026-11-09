<template>
  <div class="inspector" role="region" aria-label="Node inspector">
    <div class="inspector-head">
      <span class="inspector-title">{{ nodeTitle }}</span>
      <div class="inspector-tabs" role="tablist" aria-label="Inspector tabs">
        <button
          v-for="tab in tabs"
          :key="tab"
          role="tab"
          :aria-selected="activeTab === tab"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >{{ tab }}</button>
      </div>
    </div>
    <div class="inspector-body">
      <div v-if="activeTab === 'General'" class="section" aria-label="General settings">
        <div class="field"><label :for="`ins-field-${nodeId}-step-id`" class="label">Step ID</label><input :id="`ins-field-${nodeId}-step-id`" v-model="patch.id" class="input" /></div>
        <div class="field"><label :for="`ins-field-${nodeId}-type`" class="label">Type</label><select :id="`ins-field-${nodeId}-type`" v-model="patch.type" class="input"><option v-for="t in stepTypes" :key="t" :value="t">{{ t }}</option></select></div>
        <div class="field"><label :for="`ins-field-${nodeId}-tool`" class="label">Tool / module</label><input :id="`ins-field-${nodeId}-tool`" v-model="patch.tool" class="input" placeholder="e.g. nmap" /></div>
        <div class="field"><label :for="`ins-field-${nodeId}-command`" class="label">Command (shell)</label><input :id="`ins-field-${nodeId}-command`" v-model="patch.command" class="input" placeholder="nmap -sV {{target}}" /></div>
        <div class="field"><label :for="`ins-field-${nodeId}-depends`" class="label">Depends on</label>
          <div class="chips">
            <span v-for="d in patchDependsOn" :key="d" class="chip removable" @click.stop="removeDep(d)">{{ d }} <span class="remove" @click.stop="removeDep(d)">×</span></span>
            <input :id="`ins-field-${nodeId}-newdep`" v-model="newDep" class="input" @keydown.enter="addDep" placeholder="add step id…" style="width:120px" />
          </div>
        </div>
        <div class="field"><label :for="`ins-field-${nodeId}-when`" class="label">Condition (when)</label><input :id="`ins-field-${nodeId}-when`" v-model="patch.when" class="input" placeholder="resolve.count > 0" /></div>
        <div class="field row"><label :for="`ins-field-${nodeId}-checkpoint`" class="label">Checkpoint</label><input :id="`ins-field-${nodeId}-checkpoint`" type="checkbox" v-model="patch.checkpoint" class="checkbox" /></div>
        <div class="field row"><label :for="`ins-field-${nodeId}-onfailure`" class="label">On failure</label><select :id="`ins-field-${nodeId}-onfailure`" v-model="patch.on_failure" class="input"><option>abort</option><option>continue</option><option>skip_dependents</option></select></div>
        <div class="field"><label :for="`ins-field-${nodeId}-retry`" class="label">Retry</label><input :id="`ins-field-${nodeId}-retry`" type="number" v-model.number="patch.retry" class="input" min="0" /></div>
      </div>

      <div v-if="activeTab === 'Inputs'" class="section" aria-label="Input mapping">
        <div class="field"><label class="label">Input mapping (args)</label><p class="dim">Literal values and {{name}} references passed to the step.</p></div>
        <div class="arg-list">
          <div v-for="(val, key) in patchArgs" :key="key" class="arg-row">
            <input :id="`ins-arg-key-${key}`" v-model="argKeys[key]" class="input arg-key" :placeholder="'arg_' + (keyIndex(key)+1)" />
            <span class="arg-colon">:</span>
            <input :id="`ins-arg-val-${key}`" v-model="argValues[key]" class="input arg-val" />
            <button class="btn danger" @click="removeArg(key)" style="height:auto;padding:2px 8px;font-size:11px">×</button>
          </div>
          <div class="field row" style="margin-top:8px"><label class="label">Add input</label>
            <input :id="`ins-newarg-key`" v-model="newArgKey" class="input" placeholder="name" style="width:110px" />
            <input :id="`ins-newarg-val`" v-model="newArgVal" class="input" placeholder="value" style="flex:1" />
            <button class="btn" @click="addArg" style="height:auto">Add</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'Outputs'" class="section" aria-label="Output mapping">
        <div class="field"><label class="label">Output filter</label><p class="dim">Extract fields from step output (stdout/stderr/exit_code).</p></div>
        <div class="arg-list">
          <div v-for="(val, key) in patchFilter" :key="key" class="arg-row">
            <input :id="`ins-filter-key-${key}`" v-model="filterKeys[key]" class="input arg-key" placeholder="field" />
            <span class="arg-colon">:</span>
            <input :id="`ins-filter-val-${key}`" v-model="filterValues[key]" class="input arg-val" placeholder="jsonpath or literal" />
            <button class="btn danger" @click="removeFilter(key)" style="height:auto;padding:2px 8px;font-size:11px">×</button>
          </div>
        </div>
        <div class="field"><label class="label">Output mapping</label><p class="dim">Map step outputs to downstream references.</p></div>
        <div class="arg-list">
          <div v-for="(val, key) in patchOutputMapping" :key="key" class="arg-row">
            <input :id="`ins-out-key-${key}`" v-model="outKeys[key]" class="input arg-key" placeholder="target" />
            <span class="arg-colon">:</span>
            <input :id="`ins-out-val-${key}`" v-model="outValues[key]" class="input arg-val" placeholder="source ref" />
            <button class="btn danger" @click="removeOutputMapping(key)" style="height:auto;padding:2px 8px;font-size:11px">×</button>
          </div>
        </div>
      </div>

      <div v-if="activeTab === 'Advanced'" class="section" aria-label="Advanced settings">
        <div class="field"><label :for="`ins-field-${nodeId}-execargs`" class="label">Execution args</label><textarea :id="`ins-field-${nodeId}-execargs`" v-model="patchArgsJson" class="input area" rows="3" placeholder="{}"></textarea></div>
        <div class="field"><label :for="`ins-field-${nodeId}-budget`" class="label">Budget</label><textarea :id="`ins-field-${nodeId}-budget`" v-model="patchBudgetJson" class="input area" rows="3" placeholder="{}"></textarea></div>
        <div class="field"><label :for="`ins-field-${nodeId}-foreach`" class="label">Foreach</label><input :id="`ins-field-${nodeId}-foreach`" v-model="patch.foreach" class="input" placeholder="array field" /></div>
      </div>

      <div v-if="activeTab === 'Results'" class="section result-section" aria-label="Results">
        <div class="field"><label class="label">Last execution output</label></div>
        <div v-if="nodeResult" class="result">
          <div class="result-line"><span class="result-key">status:</span> <span :class="resultStatusClass">{{ resultStatus }}</span></div>
          <div class="result-line" v-if="nodeError"><span class="result-key">error:</span> <span class="result-val err">{{ nodeError }}</span></div>
          <div class="result-line" v-if="nodeOut && nodeOut.stdout !== undefined"><span class="result-key">stdout:</span> <span class="result-val">{{ truncate(String(nodeOut.stdout), 200) }}</span></div>
          <div class="result-line" v-if="nodeOut && nodeOut.stderr !== undefined"><span class="result-key">stderr:</span> <span class="result-val">{{ truncate(String(nodeOut.stderr), 200) }}</span></div>
          <div class="result-line" v-if="nodeOut && nodeOut.exit_code !== undefined"><span class="result-key">exit_code:</span> <span class="result-val">{{ nodeOut.exit_code }}</span></div>
          <div class="result-line" v-if="nodeOut && nodeOut.duration_ms !== undefined"><span class="result-key">duration:</span> <span class="result-val">{{ nodeOut.duration_ms }} ms</span></div>
        </div>
        <div v-if="!nodeResult" class="empty">No execution output for this step yet.</div>
      </div>
    </div>
    <div class="inspector-foot" v-if="node">
      <span class="chip" :class="{ 'ck': isStatusOk }">{{ statusText }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { usePlaybookEditorStore } from "@/stores/playbook-editor";

const props = defineProps<{
  node: any;
  definition: any;
  runStatus: Record<string, string>;
  stepResults: Record<string, any>;
}>();

const emit = defineEmits<{ (e: "update", patch: any): void }>();

const store = usePlaybookEditorStore();
const stepTypes = ["tool", "shell", "scope_check", "finding_correlation", "assessment_report", "custom"];

const activeTab = ref("General");

const tabs = ref(["General", "Inputs", "Outputs", "Advanced", "Results"]);
const name = computed(() => String(node.value?.id || ""));
const truncate = (str: string, maxLen: number) => (str.length > maxLen ? `${str.slice(0, maxLen)}…` : str);

const node = computed(() => props.node);
const nodeId = computed(() => String(node.value?.id || "node"));
const patch = ref<any>({});
const newDep = ref("");
const newArgKey = ref("");
const newArgVal = ref("");

/* Derive per-tab working objects from the node so edits are batched until emitted. */
const patchDependsOn = computed(() => Array.isArray(patch.value.depends_on) ? [...patch.value.depends_on] : []);

const patchArgs = computed<Record<string, unknown>>(() => patch.value.args ?? {});
const patchFilter = computed<Record<string, unknown>>(() => patch.value.filter ?? {});
const patchOutputMapping = computed<Record<string, unknown>>(() => patch.value.output_mapping ?? {});

/* Key/value maps used by v-model inputs in the Inputs/Outputs tabs. */
const argKeys = computed<Record<string, string>>({
  get: () => Object.fromEntries(Object.entries(patch.value.args ?? {}).map(([k]) => [k, k])),
  set: (v) => { patch.value.args = Object.fromEntries(Object.entries(v).map(([k]) => [k, (patch.value.args ?? {})[k]])); },
});
const argValues = computed<Record<string, string>>({
  get: () => (patch.value.args ?? {}) as Record<string, string>,
  set: (v) => { patch.value.args = v; },
});
const filterKeys = computed<Record<string, string>>({
  get: () => Object.fromEntries(Object.entries(patch.value.filter ?? {}).map(([k]) => [k, k])),
  set: () => {},
});
const filterValues = computed<Record<string, string>>({
  get: () => (patch.value.filter ?? {}) as Record<string, string>,
  set: (v) => { patch.value.filter = v; },
});
const outKeys = computed<Record<string, string>>({
  get: () => Object.fromEntries(Object.entries(patch.value.output_mapping ?? {}).map(([k]) => [k, k])),
  set: () => {},
});
const outValues = computed<Record<string, string>>({
  get: () => (patch.value.output_mapping ?? {}) as Record<string, string>,
  set: (v) => { patch.value.output_mapping = v; },
});

const patchArgsJson = ref("{}");
const patchBudgetJson = ref("{}");
const patchForeach = ref("");

const nodeResult = computed(() => props.stepResults[node.value?.id]);
const nodeError = computed(() => nodeResult.value?.error);
const nodeOut = computed(() => nodeResult.value?.outputs);
const resultStatus = computed(() => props.runStatus[node.value?.id] ?? "—");
const isStatusOk = computed(() => resultStatus.value === "completed");
const statusText = computed(() => resultStatus.value);
const resultStatusClass = computed(() => {
  const st = resultStatus.value;
  if (st === "completed") return "ok";
  if (st === "running" || st === "pending") return "run-run";
  return "failed";
});

const nodeTitle = computed(() => (node.value?.id || "Select a node") + ` · ${node.value?.type || ""}`);

watch(() => node.value, (nv) => {
  if (!nv) { patch.value = {}; return; }
  patch.value = JSON.parse(JSON.stringify(nv)); // deep copy
  patchArgsJson.value = JSON.stringify(nv.args ?? {}, null, 2);
  patchBudgetJson.value = JSON.stringify(nv.budget ?? {}, null, 2);
}, { immediate: true });

function keyIndex(key: string) { return Object.keys(patch.value.args ?? {}).indexOf(key); }

function addDep() {
  const d = newDep.value.trim();
  if (!d || patchDependsOn.value.includes(d)) { newDep.value = ""; return; }
  patchDependsOn.value.push(d);
  newDep.value = "";
  emit("update", { ...patch.value, depends_on: patchDependsOn.value });
}

function removeDep(d: string) {
  patchDependsOn.value.splice(patchDependsOn.value.indexOf(d), 1);
  emit("update", { ...patch.value, depends_on: patchDependsOn.value });
}

function addArg() {
  const k = newArgKey.value.trim();
  if (!k) return;
  patch.value.args = { ...(patch.value.args ?? {}), [k]: newArgVal.value };
  newArgKey.value = ""; newArgVal.value = "";
  emit("update", { ...patch.value });
}

function removeArg(key: string) {
  const next = { ...(patch.value.args ?? {}) };
  delete next[key];
  patch.value.args = next;
  emit("update", { ...patch.value });
}

function removeFilter(key: string) {
  const next = { ...(patch.value.filter ?? {}) };
  delete next[key];
  patch.value.filter = next;
  emit("update", { ...patch.value });
}

function removeOutputMapping(key: string) {
  const next = { ...(patch.value.output_mapping ?? {}) };
  delete next[key];
  patch.value.output_mapping = next;
  emit("update", { ...patch.value });
}

watch(
  () => patch.value,
  () => emit("update", { ...patch.value }),
  { deep: true },
);
</script>

<style scoped>
.inspector { display: flex; flex-direction: column; height: 100%; }
.inspector-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 12px; border-bottom: 1px solid var(--line); background: var(--panel2); flex-shrink: 0; }
.inspector-title { font-size: 13px; font-weight: 700; color: var(--text); }
.inspector-tabs { display: flex; gap: 2px; }
.inspector-tabs button { font-size: 11.5px; padding: 4px 10px; border: 1px solid transparent; border-bottom: none; background: transparent; color: var(--muted); border-radius: 0; }
.inspector-tabs button.active { color: var(--green); border-color: var(--line) var(--line) var(--panel2); background: var(--panel2); font-weight: 600; }
.inspector-body { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 12px; }
.section { display: flex; flex-direction: column; gap: 8px; }
.field { display: flex; flex-direction: column; gap: 5px; }
.field.row { flex-direction: row; align-items: center; gap: 10px; }
.field.row .input { flex: 1; }
.label { font-size: 11.5px; font-weight: 600; color: var(--muted); }
.input { width: 100%; padding: 6px 8px; background: #161616; border: 1px solid var(--line); border-radius: var(--radius-sm); color: var(--text); font-size: 12.5px; }
.input:focus { outline: none; border-color: var(--green-strong); }
.select { width: 100%; }
.checkbox { width: 16px; height: 16px; accent-color: var(--green-strong); }
.area { font-family: ui-monospace, Menlo, monospace; font-size: 12px; resize: vertical; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.chip { font-size: 11px; padding: 2px 7px; border: 1px solid var(--line); border-radius: 10px; color: var(--muted); background: var(--panel); display: inline-flex; align-items: center; gap: 5px; }
.chip.ck { border-color: #2c5743; background: var(--green2); color: var(--green); }
.remove { color: var(--red); font-weight: 700; cursor: pointer; font-size: 13px; line-height: 1; }
.chip.removable { padding-right: 2px; }
.arg-list { display: flex; flex-direction: column; gap: 6px; }
.arg-row { display: flex; gap: 6px; align-items: center; }
.arg-key { width: 150px; }
.arg-val { flex: 1; }
.arg-colon { font-size: 12px; color: var(--dim); width: 8px; text-align: center; }
.result-section { border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 10px; background: #0c1018; }
.result { display: flex; flex-direction: column; gap: 4px; font-family: ui-monospace, Menlo, monospace; font-size: 11.5px; }
.result-line { display: flex; gap: 8px; }
.result-key { color: var(--dim); min-width: 70px; }
.result-val { color: var(--text); }
.result-val.err { color: var(--red); }
.empty { color: var(--dim); font-size: 12px; font-style: italic; }
.inspector-foot { padding: 8px 12px; border-top: 1px solid var(--line); background: var(--panel2); font-size: 12px; color: var(--muted); }
</style>
