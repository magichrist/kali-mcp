<script setup lang="ts">
import { useRoute, useRouter, onBeforeRouteLeave } from "vue-router";
import { useAuthStore } from "@/stores/auth";
import { ref } from "vue";
import Sidebar from "@/components/layout/Sidebar.vue";
import Topbar from "@/components/layout/Topbar.vue";
import Breadcrumbs from "@/components/layout/Breadcrumbs.vue";
import PageContainer from "@/components/layout/PageContainer.vue";
import ToastContainer from "@/components/common/ToastContainer.vue";
import ConfirmDialog from "@/components/common/ConfirmDialog.vue";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();

const sidebarMinimized = ref(
  typeof localStorage !== "undefined"
    ? localStorage.getItem("kmcp_sidebar_minimized") === "1"
    : false
);

const confirmOpen = ref(false);

function toggleSidebar(): void {
  sidebarMinimized.value = !sidebarMinimized.value;
  if (typeof localStorage !== "undefined") {
    localStorage.setItem("kmcp_sidebar_minimized", sidebarMinimized.value ? "1" : "0");
  }
}

onBeforeRouteLeave((_to, _from) => {
  const page = _from.meta?.pageCleanup;
  if (typeof page === "function") {
    page();
  }
});
</script>

<template>
  <div class="app" :class="{ 'sidebar-minimized': sidebarMinimized }" id="app">
    <Sidebar :minimized="sidebarMinimized" @toggle="toggleSidebar" />
    <main class="main">
      <Topbar />
      <Breadcrumbs />
      <PageContainer>
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </PageContainer>
    </main>
    <ToastContainer />
    <ConfirmDialog v-model:open="confirmOpen" />
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.12s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
