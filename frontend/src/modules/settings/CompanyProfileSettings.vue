<script setup lang="ts">
// Company details printed on the commercial documents - proformas, delivery
// notes, loading sheets, purchase orders (spec 2026-10-11
// documents-commerciaux §2). Singleton, admin module.
import { ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppAlert from '@/components/ui/AppAlert.vue'
import Button from '@/components/ui/Button.vue'
import { fetchCompanyProfile, updateCompanyProfile } from './api'
import type { CompanyBankAccount, CompanyProfile } from './types'

const { t } = useI18n()

type TextField = Exclude<keyof CompanyProfile, 'bank_accounts'>
const FIELDS: { key: TextField; label: string; wide?: boolean }[] = [
  { key: 'name', label: 'name' },
  { key: 'tagline', label: 'tagline' },
  { key: 'tax_id', label: 'taxId' },
  { key: 'trade_register', label: 'tradeRegister' },
  { key: 'address', label: 'address', wide: true },
  { key: 'city', label: 'city' },
  { key: 'phone', label: 'phone' },
  { key: 'email', label: 'email' },
  { key: 'website', label: 'website' },
]

const profile = ref<CompanyProfile | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const saved = ref(false)

const inputClass =
  'border-ligne-forte h-11 w-full rounded-lg border bg-white px-3 focus-visible:outline-bitume focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'

onMounted(async () => {
  try {
    profile.value = await fetchCompanyProfile()
  } catch {
    error.value = t('settings.company.loadError')
  } finally {
    loading.value = false
  }
})

function addBank() {
  profile.value?.bank_accounts.push({ bank: '', swift: '', account_number: '', is_active: true })
}

function removeBank(index: number) {
  profile.value?.bank_accounts.splice(index, 1)
}

async function onSubmit() {
  if (!profile.value) return
  saving.value = true
  saved.value = false
  error.value = ''
  try {
    const bank_accounts: CompanyBankAccount[] = profile.value.bank_accounts.map((b) => ({
      bank: b.bank,
      swift: b.swift,
      account_number: b.account_number,
      is_active: b.is_active,
    }))
    profile.value = await updateCompanyProfile({ ...profile.value, bank_accounts })
    saved.value = true
  } catch {
    error.value = t('settings.company.saveError')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="max-w-4xl space-y-6">
    <div>
      <h1 class="font-display text-2xl leading-none font-semibold uppercase">
        {{ t('settings.company.title') }}
      </h1>
      <p class="text-texte-2 mt-2 text-sm">{{ t('settings.company.description') }}</p>
    </div>

    <AppAlert v-if="error" :message="error" />
    <p v-if="saved" class="text-sm font-medium text-emerald-700">
      {{ t('settings.company.saved') }}
    </p>
    <p v-if="loading" class="text-texte-3 text-sm">{{ t('common.loading') }}</p>

    <form v-else-if="profile" class="space-y-6" @submit.prevent="onSubmit">
      <section class="border-ligne space-y-4 rounded-xl border bg-surface p-6">
        <h2 class="font-semibold">{{ t('settings.company.contact') }}</h2>
        <div class="grid gap-4 sm:grid-cols-2">
          <div
            v-for="field in FIELDS"
            :key="field.key"
            class="space-y-1.5"
            :class="field.wide ? 'sm:col-span-2' : ''"
          >
            <label class="text-texte-2 text-sm font-medium" :for="`company-${field.key}`">
              {{ t(`settings.company.${field.label}`) }}
            </label>
            <input
              :id="`company-${field.key}`"
              v-model="profile[field.key]"
              type="text"
              :class="inputClass"
            />
          </div>
        </div>
      </section>

      <section class="border-ligne space-y-4 rounded-xl border bg-surface p-6">
        <div>
          <h2 class="font-semibold">{{ t('settings.company.banks') }}</h2>
          <p class="text-texte-3 text-xs">{{ t('settings.company.banksHelp') }}</p>
        </div>
        <p v-if="!profile.bank_accounts.length" class="text-texte-3 text-sm">
          {{ t('settings.company.noBanks') }}
        </p>
        <div
          v-for="(bank, index) in profile.bank_accounts"
          :key="index"
          class="grid items-end gap-3 sm:grid-cols-[1fr_1fr_1.5fr_auto_auto]"
        >
          <label class="space-y-1 text-sm">
            <span class="text-texte-2">{{ t('settings.company.bank') }}</span>
            <input
              v-model="bank.bank"
              :data-test="`bank-${index}-bank`"
              required
              :class="inputClass"
            />
          </label>
          <label class="space-y-1 text-sm">
            <span class="text-texte-2">{{ t('settings.company.swift') }}</span>
            <input v-model="bank.swift" :class="inputClass" />
          </label>
          <label class="space-y-1 text-sm">
            <span class="text-texte-2">{{ t('settings.company.accountNumber') }}</span>
            <input
              v-model="bank.account_number"
              :data-test="`bank-${index}-account`"
              required
              :class="inputClass"
            />
          </label>
          <label class="flex h-11 items-center gap-2 text-sm">
            <input v-model="bank.is_active" type="checkbox" />
            {{ t('settings.company.active') }}
          </label>
          <Button type="button" variant="ghost" @click="removeBank(index)">
            {{ t('settings.company.removeBank') }}
          </Button>
        </div>
        <Button type="button" variant="secondary" data-test="add-bank" @click="addBank">
          {{ t('settings.company.addBank') }}
        </Button>
      </section>

      <div class="flex justify-end">
        <Button type="submit" variant="primary" :loading="saving">
          {{ saving ? t('settings.company.saving') : t('settings.company.save') }}
        </Button>
      </div>
    </form>
  </div>
</template>
