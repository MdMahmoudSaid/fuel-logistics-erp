<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

function onLogout() {
  auth.logout()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="min-h-screen bg-slate-50">
    <header class="flex items-center justify-between border-b bg-white px-6 py-3 shadow-sm">
      <span class="font-semibold text-slate-800">Fuel Logistics ERP</span>
      <div class="flex items-center gap-4 text-sm text-slate-600">
        <span v-if="auth.user"
          >{{ auth.user.full_name || auth.user.email }} · {{ auth.user.role }}</span
        >
        <button class="text-slate-500 hover:text-slate-800" @click="onLogout">Log out</button>
      </div>
    </header>
    <main class="p-6">
      <p class="text-slate-500">
        Dashboard and module navigation land here as each roadmap phase is implemented.
      </p>
    </main>
  </div>
</template>
