<script setup lang="ts">
// Live estimate of a quantity shortfall: how much the company absorbs (up to the
// loss tolerance) and how much is chargeable to the transporter. Shown under the
// received-quantity field wherever one is typed (Ventes popup, "Saisir la
// quantité reçue", client verification). Only an estimate: the server freezes the
// real tolerance when it records the quantity.
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchLossTolerance } from '@/modules/settings/api'
import { formatQuantity } from '@/utils/currency'

const props = defineProps<{ quantityLoaded: string | number; receivedQuantity: string | number }>()
const { t } = useI18n()

const DEFAULT_TOLERANCE_LITRES = 100
const toleranceLitres = ref(DEFAULT_TOLERANCE_LITRES)

onMounted(async () => {
  try {
    const config = await fetchLossTolerance()
    toleranceLitres.value = Number(config.tolerance_litres)
  } catch {
    // Not allowed to read the setting (or the request failed): keep the default
    // for the live estimate.
  }
})

const hasReceived = computed(() => String(props.receivedQuantity ?? '') !== '')
const lossQty = computed(() => Number(props.quantityLoaded) - (Number(props.receivedQuantity) || 0))
const companyAbsorbedQty = computed(() =>
  Math.max(Math.min(lossQty.value, toleranceLitres.value), 0),
)
const transporterChargeableQty = computed(() => Math.max(lossQty.value - toleranceLitres.value, 0))
</script>

<template>
  <div
    v-if="hasReceived"
    data-test="loss-estimate"
    class="border-ligne grid grid-cols-1 gap-4 rounded-lg border bg-sable p-3 text-sm md:grid-cols-2"
  >
    <div>
      <span class="text-texte-2">{{ t('trips.clientVerification.companyAbsorbed') }}</span>
      <p class="text-texte font-medium" data-test="company-absorbed">
        {{ formatQuantity(companyAbsorbedQty) }}
      </p>
    </div>
    <div>
      <span class="text-texte-2">{{ t('trips.clientVerification.transporterChargeable') }}</span>
      <p class="text-texte font-medium" data-test="transporter-chargeable">
        {{ formatQuantity(transporterChargeableQty) }}
      </p>
    </div>
  </div>
</template>
