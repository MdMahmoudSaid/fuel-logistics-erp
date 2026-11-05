<script setup lang="ts">
// "⋯" button opening a small menu of secondary row actions. The menu is
// teleported to <body> with fixed positioning so the table's horizontal
// scroll container cannot clip it.
import { nextTick, onBeforeUnmount, ref } from 'vue'

defineProps<{
  items: { key: string; label: string; tone?: string }[]
  label: string
}>()

const emit = defineEmits<{ select: [key: string] }>()

const open = ref(false)
const trigger = ref<HTMLButtonElement | null>(null)
const menu = ref<HTMLElement | null>(null)
const pos = ref({ top: 0, left: 0 })

function close() {
  open.value = false
  document.removeEventListener('click', onOutside, true)
  window.removeEventListener('scroll', close, true)
  window.removeEventListener('resize', close)
}

function onOutside(e: Event) {
  const target = e.target as Node
  if (menu.value?.contains(target) || trigger.value?.contains(target)) return
  close()
}

async function toggle() {
  if (open.value) return close()
  const rect = trigger.value!.getBoundingClientRect()
  open.value = true
  pos.value = { top: rect.bottom + 4, left: rect.right }
  document.addEventListener('click', onOutside, true)
  window.addEventListener('scroll', close, true)
  window.addEventListener('resize', close)
  await nextTick()
  // Right-align the menu on the trigger.
  const width = menu.value?.offsetWidth ?? 0
  pos.value = { top: pos.value.top, left: Math.max(8, rect.right - width) }
}

function pick(key: string) {
  close()
  emit('select', key)
}

onBeforeUnmount(close)
</script>

<template>
  <button
    ref="trigger"
    type="button"
    :aria-label="label"
    aria-haspopup="menu"
    :aria-expanded="open"
    class="text-texte-2 hover:text-texte hover:bg-sable inline-flex h-7 w-7 items-center justify-center rounded-md text-lg leading-none"
    @click="toggle"
  >
    ⋯
  </button>
  <Teleport to="body">
    <div
      v-if="open"
      ref="menu"
      role="menu"
      class="border-ligne-forte fixed z-50 min-w-40 rounded-lg border bg-white py-1 shadow-lg"
      :style="{ top: `${pos.top}px`, left: `${pos.left}px` }"
    >
      <button
        v-for="item in items"
        :key="item.key"
        type="button"
        role="menuitem"
        class="hover:bg-sable block w-full px-3 py-2 text-start text-sm whitespace-nowrap"
        :class="item.tone"
        @click="pick(item.key)"
      >
        {{ item.label }}
      </button>
    </div>
  </Teleport>
</template>
