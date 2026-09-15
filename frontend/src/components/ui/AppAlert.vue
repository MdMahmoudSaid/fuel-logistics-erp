<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  dismissAlertNotification,
  showAlertNotification,
  type AlertVariant,
} from '@/composables/useAlertNotification'

const props = withDefaults(defineProps<{ message: string; variant?: AlertVariant }>(), {
  variant: 'error',
})
const element = ref<HTMLElement | null>(null)
const owner = Symbol('alert')
let scope: HTMLElement | null = null
let mounted = false

function announce() {
  if (!mounted || !props.message) return
  showAlertNotification({
    owner,
    message: props.message,
    variant: props.variant,
  })
}

// Synchronous validation can clear and set the same error within one Vue
// update. A submit listener also reopens a dismissed alert in that case.
async function onSubmit() {
  await nextTick()
  announce()
}

onMounted(() => {
  mounted = true
  scope = element.value?.closest('form') ?? element.value?.parentElement ?? null
  scope?.addEventListener('submit', onSubmit)
  announce()
})

watch(
  () => [props.message, props.variant],
  () => {
    if (props.message) announce()
    else dismissAlertNotification(owner)
  },
  { flush: 'post' },
)

onBeforeUnmount(() => {
  mounted = false
  scope?.removeEventListener('submit', onSubmit)
  dismissAlertNotification(owner)
})
</script>

<template>
  <span ref="element" hidden aria-hidden="true" role="alert" class="text-critique">{{
    message
  }}</span>
</template>
