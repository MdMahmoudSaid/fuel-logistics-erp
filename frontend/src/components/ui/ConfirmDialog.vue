<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { confirmRequest, resolveConfirmDialog } from '@/composables/useConfirmDialog'

const { t } = useI18n()
const dialog = ref<HTMLDialogElement | null>(null)
const confirmButton = ref<HTMLButtonElement | null>(null)
let returnFocus: HTMLElement | null = null

watch(
  confirmRequest,
  async () => {
    await nextTick()
    if (!dialog.value) return
    if (confirmRequest.value) {
      if (!dialog.value.open) {
        returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
        dialog.value.showModal()
      }
      confirmButton.value?.focus({ preventScroll: true })
    } else {
      dialog.value.close()
      if (returnFocus?.isConnected) returnFocus.focus({ preventScroll: true })
      returnFocus = null
    }
  },
  { immediate: true, flush: 'post' },
)

onBeforeUnmount(() => dialog.value?.close())
</script>

<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="error-popup no-print"
      role="alertdialog"
      aria-modal="true"
      aria-describedby="confirm-popup-message"
      data-test="confirm-dialog"
      @cancel.prevent="resolveConfirmDialog(false)"
    >
      <template v-if="confirmRequest">
        <p
          id="confirm-popup-message"
          class="text-texte mt-2 whitespace-pre-line break-words text-base leading-relaxed"
        >
          {{ confirmRequest.message }}
        </p>
        <div class="mt-6 flex justify-center gap-3">
          <button
            type="button"
            class="border-ligne-forte text-texte min-h-11 min-w-28 rounded-lg border px-6 py-2.5 font-semibold hover:bg-fond"
            @click="resolveConfirmDialog(false)"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            ref="confirmButton"
            type="button"
            class="bg-bitume min-h-11 min-w-28 rounded-lg px-6 py-2.5 font-semibold text-white hover:bg-bitume-2 focus-visible:outline-2 focus-visible:outline-offset-4"
            @click="resolveConfirmDialog(true)"
          >
            {{ t('common.confirm') }}
          </button>
        </div>
      </template>
    </dialog>
  </Teleport>
</template>
