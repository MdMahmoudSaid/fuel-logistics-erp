<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppLogo from '@/components/AppLogo.vue'
import Input from '@/components/ui/Input.vue'
import Button from '@/components/ui/Button.vue'

const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(email.value, password.value)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch {
    error.value = 'Invalid email or password.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="bg-sable flex min-h-screen">
    <!-- Panneau de marque (desktop) -->
    <div
      class="bg-bitume relative hidden w-1/2 flex-col justify-between overflow-hidden p-10 lg:flex"
    >
      <AppLogo tone="light" :size="32" />
      <div class="relative z-10">
        <p class="font-display text-sable max-w-sm text-3xl leading-tight font-semibold uppercase">
          Suivi carburant, trajets &amp; trésorerie — bout en bout.
        </p>
      </div>
      <svg
        class="pointer-events-none absolute -right-24 -bottom-24 opacity-[0.08]"
        width="420"
        height="420"
        viewBox="0 0 32 32"
        fill="none"
        aria-hidden="true"
      >
        <path
          d="M9 21a7 7 0 1 1 14 0"
          stroke="#F97316"
          stroke-width="1.4"
          stroke-dasharray="1 2.2"
        />
        <line x1="16" y1="21" x2="20.2" y2="16.4" stroke="#F97316" stroke-width="1.4" />
      </svg>
    </div>

    <!-- Formulaire -->
    <div class="flex flex-1 flex-col items-center justify-center p-6">
      <div class="w-full max-w-sm">
        <div class="mb-8 flex justify-center lg:hidden">
          <AppLogo :size="32" />
        </div>

        <form
          class="bg-surface border-ligne space-y-5 rounded-xl border p-7 shadow-sm"
          @submit.prevent="onSubmit"
        >
          <div>
            <h1 class="font-display text-texte text-2xl font-semibold uppercase">Connexion</h1>
            <p class="text-texte-2 mt-1 text-sm">Accédez à votre espace opérations.</p>
          </div>

          <Input
            id="email"
            v-model="email"
            label="Email"
            type="email"
            autocomplete="username"
            required
          />
          <Input
            id="password"
            v-model="password"
            label="Mot de passe"
            type="password"
            autocomplete="current-password"
            required
          />

          <p v-if="error" class="text-critique text-sm" role="alert">{{ error }}</p>

          <Button type="submit" variant="primary" size="md" :disabled="loading" class="w-full">
            {{ loading ? 'Signing in…' : 'Sign in' }}
          </Button>
        </form>
      </div>
    </div>
  </div>
</template>
