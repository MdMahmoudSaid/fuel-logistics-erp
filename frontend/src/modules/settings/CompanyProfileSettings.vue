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

type TextField = Exclude<keyof CompanyProfile, 'bank_accounts' | 'phone' | 'email' | 'website'>
const FIELDS: { key: TextField; label: string; wide?: boolean }[] = [
  { key: 'name', label: 'name' },
  { key: 'tagline', label: 'tagline' },
  { key: 'tax_id', label: 'taxId' },
  { key: 'trade_register', label: 'tradeRegister' },
  { key: 'address', label: 'address', wide: true },
  { key: 'city', label: 'city' },
]

// Phone numbers and e-mails: any number of them, one input each (stored one
// per line by the API, printed one per line in the PDF letterhead).
const MAX_CONTACT_VALUES = 10
const phones = ref<string[]>([''])
const emails = ref<string[]>([''])
const CONTACT_LISTS = [
  { id: 'phone', values: phones, label: 'phone', add: 'addPhone', type: 'tel' },
  { id: 'email', values: emails, label: 'email', add: 'addEmail', type: 'email' },
] as const

function toList(raw: string): string[] {
  const values = (raw ?? '')
    .split('\n')
    .map((v) => v.trim())
    .filter(Boolean)
  return values.length ? values : ['']
}
function fromList(values: string[]): string {
  return values
    .map((v) => v.trim())
    .filter(Boolean)
    .join('\n')
}
function addValue(values: string[]) {
  if (values.length < MAX_CONTACT_VALUES) values.push('')
}
function removeValue(values: string[], index: number) {
  values.splice(index, 1)
  if (!values.length) values.push('')
}

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
    phones.value = toList(profile.value.phone)
    emails.value = toList(profile.value.email)
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
    profile.value = await updateCompanyProfile({
      ...profile.value,
      phone: fromList(phones.value),
      email: fromList(emails.value),
      bank_accounts,
    })
    phones.value = toList(profile.value.phone)
    emails.value = toList(profile.value.email)
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

          <div
            v-for="list in CONTACT_LISTS"
            :key="list.id"
            class="space-y-1.5"
            :data-test="`company-${list.id}-list`"
          >
            <label class="text-texte-2 text-sm font-medium" :for="`company-${list.id}-0`">
              {{ t(`settings.company.${list.label}`) }}
            </label>
            <div v-for="(_, index) in list.values.value" :key="index" class="flex gap-2">
              <input
                :id="`company-${list.id}-${index}`"
                v-model="list.values.value[index]"
                :type="list.type"
                :data-test="`company-${list.id}-${index}`"
                :class="inputClass"
              />
              <button
                v-if="list.values.value.length > 1"
                type="button"
                :data-test="`company-${list.id}-remove-${index}`"
                class="border-ligne-forte text-critique hover:bg-sable h-11 shrink-0 rounded-lg border px-3 text-sm"
                :aria-label="t('settings.company.removeValue')"
                @click="removeValue(list.values.value, index)"
              >
                ✕
              </button>
            </div>
            <button
              v-if="list.values.value.length < MAX_CONTACT_VALUES"
              type="button"
              :data-test="`company-${list.id}-add`"
              class="text-bitume hover:text-orange text-sm font-medium"
              @click="addValue(list.values.value)"
            >
              + {{ t(`settings.company.${list.add}`) }}
            </button>
          </div>

          <div class="space-y-1.5">
            <label class="text-texte-2 text-sm font-medium" for="company-website">
              {{ t('settings.company.website') }}
            </label>
            <input id="company-website" v-model="profile.website" type="text" :class="inputClass" />
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
