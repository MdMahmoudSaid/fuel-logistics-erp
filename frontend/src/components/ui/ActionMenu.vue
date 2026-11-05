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
const pos = ref({ top: 0, left: 0, maxHeight: 0 })
// Hidden until measured, so the menu never flashes in the wrong place.
const placed = ref(false)
const GAP = 4
const MARGIN = 8

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
  placed.value = false
  open.value = true
  pos.value = { top: rect.bottom + GAP, left: rect.right, maxHeight: 0 }
  document.addEventListener('click', onOutside, true)
  window.addEventListener('scroll', close, true)
  window.addEventListener('resize', close)
  await nextTick()
  // Right-align on the trigger, and open on the side with room: below the
  // button by default, above it when the row sits near the bottom of the
  // screen (the largest side, scrolling inside, if neither fits).
  const width = menu.value?.offsetWidth ?? 0
  const height = menu.value?.offsetHeight ?? 0
  const spaceBelow = window.innerHeight - rect.bottom - GAP - MARGIN
  const spaceAbove = rect.top - GAP - MARGIN
  let top = rect.bottom + GAP
  let maxHeight = 0
  if (height > spaceBelow) {
    if (height <= spaceAbove) {
      top = rect.top - GAP - height
    } else if (spaceAbove > spaceBelow) {
      maxHeight = Math.max(spaceAbove, 80)
      top = rect.top - GAP - maxHeight
    } else {
      maxHeight = Math.max(spaceBelow, 80)
    }
  }
  pos.value = { top, left: Math.max(MARGIN, rect.right - width), maxHeight }
  placed.value = true
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
      class="border-ligne-forte fixed z-50 min-w-40 overflow-y-auto rounded-lg border bg-white py-1 shadow-lg"
      :style="{
        top: `${pos.top}px`,
        left: `${pos.left}px`,
        visibility: placed ? 'visible' : 'hidden',
        maxHeight: pos.maxHeight ? `${pos.maxHeight}px` : undefined,
      }"
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
