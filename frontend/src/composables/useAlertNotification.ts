import { shallowRef } from 'vue'

export type AlertVariant = 'error' | 'warning' | 'success'

interface AlertNotification {
  owner: symbol
  message: string
  variant: AlertVariant
}

// One active error popup shared by every form.
export const alertNotification = shallowRef<AlertNotification | null>(null)

export function showAlertNotification(notification: AlertNotification) {
  alertNotification.value = notification
}

export function dismissAlertNotification(owner?: symbol) {
  if (!owner || alertNotification.value?.owner === owner) {
    alertNotification.value = null
  }
}
