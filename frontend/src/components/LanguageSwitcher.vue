<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { AVAILABLE_LOCALES, setLocale, type AppLocale } from '@/i18n'

defineOptions({ name: 'LanguageSwitcher' })

const { locale, t } = useI18n()
</script>

<template>
  <div
    class="border-ligne-forte inline-flex h-9 items-center rounded-full border bg-white p-0.5 text-xs font-medium"
    role="group"
    :aria-label="t('header.languageLabel')"
  >
    <button
      v-for="code in AVAILABLE_LOCALES"
      :key="code"
      type="button"
      class="h-8 rounded-full px-2.5 uppercase transition"
      :class="
        locale === code ? 'bg-orange-tint text-orange-fonce' : 'text-texte-2 hover:bg-sable'
      "
      :aria-pressed="locale === code"
      @click="setLocale(code as AppLocale)"
    >
      {{ code }}
    </button>
  </div>
</template>
