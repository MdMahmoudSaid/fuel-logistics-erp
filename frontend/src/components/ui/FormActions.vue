<script setup lang="ts">
defineOptions({ name: 'UiFormActions' })
</script>

<template>
  <!--
    Barre de boutons d'un formulaire en pop-up : reste collée en bas de la
    fenêtre (qui défile, padding p-6) pour que « Enregistrer » soit toujours
    visible sans avoir à descendre. Le -bottom-6/-mx-6/-mb-6 compense le p-6
    du conteneur qui défile (UiModal, ou les fenêtres de TripDetail /
    MasterDataView).
  -->
  <div
    class="border-ligne bg-surface sticky -bottom-6 z-10 -mx-6 -mb-6 flex flex-wrap items-center justify-end gap-2 rounded-b-xl border-t px-6 py-3"
  >
    <slot />
  </div>
</template>
