<script setup lang="ts">
import AppAlert from '@/components/ui/AppAlert.vue'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import AppLogo from '@/components/AppLogo.vue'
import CountryPhoneInput from '@/components/ui/CountryPhoneInput.vue'
import Button from '@/components/ui/Button.vue'
import { blockNonDigitInput } from '@/utils/numeric-input'

const { t } = useI18n()

const phone = ref('')
const pin = ref('')
const error = ref('')
const loading = ref(false)
const showPin = ref(false)

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

function onPinInput(event: Event) {
  pin.value = (event.target as HTMLInputElement).value.replace(/\D/g, '').slice(0, 4)
}

async function onSubmit() {
  error.value = ''
  loading.value = true
  try {
    await auth.login(phone.value, pin.value)
    const redirect = (route.query.redirect as string) || '/'
    router.push(redirect)
  } catch {
    error.value = t('auth.invalidCredentials')
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
          {{ t('auth.tagline') }}
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
            <h1 class="font-display text-texte text-2xl font-semibold uppercase">
              {{ t('auth.title') }}
            </h1>
            <p class="text-texte-2 mt-1 text-sm">{{ t('auth.subtitle') }}</p>
          </div>

          <CountryPhoneInput id="phone" v-model="phone" :label="t('auth.phoneLabel')" required />

          <div class="space-y-1.5">
            <label for="pin" class="text-texte-2 text-sm font-medium">
              {{ t('auth.pinLabel') }}
            </label>
            <div class="relative">
              <input
                id="pin"
                :value="pin"
                :type="showPin ? 'text' : 'password'"
                inputmode="numeric"
                pattern="\d{4}"
                minlength="4"
                maxlength="4"
                autocomplete="current-password"
                required
                class="border-ligne-forte text-texte placeholder:text-texte-3 focus-visible:outline-bitume h-12 w-full rounded-lg border bg-white px-3.5 pr-11 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
                @beforeinput="blockNonDigitInput"
                @input="onPinInput"
              />
              <div class="absolute inset-y-0 right-1.5 flex items-center">
                <button
                  type="button"
                  class="text-texte-3 hover:text-texte-2 flex h-8 w-8 items-center justify-center rounded-md transition"
                  :aria-label="showPin ? t('auth.hidePassword') : t('auth.showPassword')"
                  @click="showPin = !showPin"
                >
                  <svg
                    v-if="showPin"
                    width="18"
                    height="18"
                    viewBox="0 0 24 24"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.4 5.5A9.9 9.9 0 0 1 12 5.2c4.2 0 7.8 2.6 9.5 6.3a10.5 10.5 0 0 1-2.9 3.7M6.5 6.9A10.6 10.6 0 0 0 2.5 11.5c1.7 3.7 5.3 6.3 9.5 6.3a9.6 9.6 0 0 0 3.4-.6"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                  <svg v-else width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                    <path
                      d="M2.5 11.5C4.2 7.8 7.8 5.2 12 5.2s7.8 2.6 9.5 6.3c-1.7 3.7-5.3 6.3-9.5 6.3s-7.8-2.6-9.5-6.3Z"
                      stroke="currentColor"
                      stroke-width="1.8"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                    <circle cx="12" cy="11.5" r="2.6" stroke="currentColor" stroke-width="1.8" />
                  </svg>
                </button>
              </div>
            </div>
          </div>

          <AppAlert v-if="error" :message="error" />

          <Button type="submit" variant="primary" size="md" :disabled="loading" class="w-full">
            {{ loading ? t('auth.signingIn') : t('auth.signIn') }}
          </Button>
        </form>
      </div>
    </div>
  </div>
</template>
