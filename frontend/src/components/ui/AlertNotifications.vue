<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { alertNotification, dismissAlertNotification } from '@/composables/useAlertNotification'

const dialog = ref<HTMLDialogElement | null>(null)
const okButton = ref<HTMLButtonElement | null>(null)
let returnFocus: HTMLElement | null = null

watch(
  alertNotification,
  async () => {
    await nextTick()
    if (!dialog.value) return
    if (alertNotification.value) {
      if (!dialog.value.open) {
        returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
        dialog.value.showModal()
      }
      okButton.value?.focus({ preventScroll: true })
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
      aria-labelledby="error-popup-title"
      aria-describedby="error-popup-message"
      :data-test="alertNotification ? 'alert-notification' : undefined"
      @cancel.prevent="dismissAlertNotification()"
    >
      <template v-if="alertNotification">
        <span
          class="error-popup__icon"
          :class="`error-popup__icon--${alertNotification.variant}`"
          aria-hidden="true"
        >
          {{ alertNotification.variant === 'success' ? '✓' : '!' }}
        </span>
        <h2 id="error-popup-title" class="mt-4 text-xl font-semibold">
          {{ $t(`alerts.${alertNotification.variant}Title`) }}
        </h2>
        <p
          id="error-popup-message"
          class="text-texte-2 mt-3 whitespace-pre-line break-words text-base leading-relaxed"
        >
          {{ alertNotification.message }}
        </p>
        <button
          ref="okButton"
          type="button"
          class="bg-bitume text-white mt-6 min-h-11 min-w-28 rounded-lg px-6 py-2.5 font-semibold hover:bg-bitume-2 focus-visible:outline-2 focus-visible:outline-offset-4"
          @click="dismissAlertNotification()"
        >
          {{ $t('alerts.ok') }}
        </button>
      </template>
    </dialog>
  </Teleport>
</template>
