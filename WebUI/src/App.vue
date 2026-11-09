<script setup lang="ts">
import { onMounted } from "vue";
import { useAuthStore } from "@/stores/auth";

const auth = useAuthStore();

onMounted(() => {
  void auth.checkAuth();
});
</script>

<template>
  <StudioLayout />
</template>

<script lang="ts">
import { defineComponent } from "vue";
import StudioLayout from "@/layouts/StudioLayout.vue";

export default defineComponent({
  components: { StudioLayout },
});
</script>
