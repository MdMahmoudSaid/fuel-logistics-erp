<script setup lang="ts">
import { onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import AlertNotifications from '@/components/ui/AlertNotifications.vue'
import ConfirmDialog from '@/components/ui/ConfirmDialog.vue'

const auth = useAuthStore()

// A page reload (or opening a deep link directly) re-creates the Pinia
// store from scratch: accessToken/refreshToken survive via localStorage,
// but `user` does not — only the login() action populates it. Without this,
// auth.can(...) and auth.user reads (nav visibility, the header greeting,
// TripDetail's status-change gate, ...) silently see a logged-in-but-
// user-less state on every reload. Hydrate it once here; an invalid/expired
// token surfaces as a fetchMe() failure, so log out rather than leave a
// half-authenticated session.
onMounted(() => {
  if (auth.accessToken && !auth.user) {
    auth.fetchMe().catch(() => auth.logout())
  }
})
</script>

<template>
  <router-view />
  <AlertNotifications />
  <ConfirmDialog />
</template>
