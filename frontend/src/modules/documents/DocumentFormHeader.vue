<script setup lang="ts">
// Title + PDF / Print / Back actions shared by the document forms.
import { useI18n } from 'vue-i18n'
import Button from '@/components/ui/Button.vue'

defineProps<{ title: string; saved: boolean; busy: boolean }>()
defineEmits<{ pdf: []; print: []; back: [] }>()
const { t } = useI18n()
</script>

<template>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
    <h1 class="font-display text-2xl leading-none font-semibold uppercase">{{ title }}</h1>
    <div class="flex flex-wrap gap-2">
      <template v-if="saved">
        <Button
          variant="secondary"
          type="button"
          :disabled="busy"
          data-test="doc-form-pdf"
          @click="$emit('pdf')"
        >
          {{ t('documents.common.pdf') }}
        </Button>
        <Button
          variant="secondary"
          type="button"
          :disabled="busy"
          data-test="doc-form-print"
          @click="$emit('print')"
        >
          {{ t('documents.common.print') }}
        </Button>
      </template>
      <Button variant="ghost" type="button" @click="$emit('back')">{{
        t('documents.common.back')
      }}</Button>
    </div>
  </div>
</template>
