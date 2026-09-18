import { shallowRef } from 'vue'

interface ConfirmRequest {
  message: string
  resolve: (value: boolean) => void
}

// One active confirm popup shared by every view - mirrors
// useAlertNotification's module-scoped singleton so ConfirmDialog.vue
// (mounted once in App.vue) can render it without prop drilling.
export const confirmRequest = shallowRef<ConfirmRequest | null>(null)

// Bug fix (2026-09-18): destructive actions (cancel/delete a paid fee...)
// used window.confirm(), which renders as a native browser/OS dialog (the
// "localhost says" prompt) instead of the app's own popup style every
// other alert already uses. Same call shape as window.confirm - await the
// boolean instead of reading it synchronously.
export function confirmDialog(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    confirmRequest.value = { message, resolve }
  })
}

export function resolveConfirmDialog(value: boolean) {
  confirmRequest.value?.resolve(value)
  confirmRequest.value = null
}
