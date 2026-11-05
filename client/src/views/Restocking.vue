<template>
  <div class="restocking">
    <div class="page-header">
      <h2>{{ t('restocking.title') }}</h2>
      <p>{{ t('restocking.description') }}</p>
    </div>

    <div v-if="loading" class="loading">{{ t('common.loading') }}</div>
    <div v-else-if="error" class="error">{{ error }}</div>
    <div v-else>
      <div class="card budget-card">
        <div class="budget-row">
          <label class="budget-label" for="budget-slider">{{ t('restocking.budgetLabel') }}</label>
          <span class="budget-value">{{ formatMoney(budget) }}</span>
        </div>
        <input
          id="budget-slider"
          v-model.number="budget"
          class="budget-slider"
          type="range"
          min="0"
          :max="maxBudget"
          :step="budgetStep"
        />
        <div class="budget-scale">
          <span>{{ formatMoney(0) }}</span>
          <span>{{ formatMoney(maxBudget) }}</span>
        </div>
      </div>

      <div class="stats-grid">
        <div class="stat-card info">
          <div class="stat-label">{{ t('restocking.budget') }}</div>
          <div class="stat-value">{{ formatMoney(budget) }}</div>
        </div>
        <div class="stat-card warning">
          <div class="stat-label">{{ t('restocking.totalSpend') }}</div>
          <div class="stat-value">{{ formatMoney(totalSpend) }}</div>
        </div>
        <div class="stat-card success">
          <div class="stat-label">{{ t('restocking.remaining') }}</div>
          <div class="stat-value">{{ formatMoney(remainingBudget) }}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h3 class="card-title">{{ t('restocking.recommendedItems') }} ({{ recommendations.length }})</h3>
          <button
            class="place-order-btn"
            type="button"
            :disabled="recommendations.length === 0 || submitting"
            @click="placeOrder"
          >
            {{ submitting ? t('restocking.submitting') : t('restocking.placeOrder') }}
          </button>
        </div>

        <div v-if="successMessage" class="message success-message">{{ successMessage }}</div>
        <div v-if="submitError" class="message error-message">{{ submitError }}</div>

        <div v-if="recommendations.length === 0" class="empty-state">
          {{ t('restocking.empty') }}
        </div>
        <div v-else class="table-container">
          <table>
            <thead>
              <tr>
                <th>{{ t('restocking.table.sku') }}</th>
                <th>{{ t('restocking.table.itemName') }}</th>
                <th>{{ t('restocking.table.trend') }}</th>
                <th class="num">{{ t('restocking.table.quantity') }}</th>
                <th class="num">{{ t('restocking.table.unitCost') }}</th>
                <th class="num">{{ t('restocking.table.lineTotal') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="rec in recommendations" :key="rec.sku">
                <td><strong>{{ rec.sku }}</strong></td>
                <td>{{ translateProductName(rec.name) }}</td>
                <td>
                  <span :class="['badge', rec.trend]">{{ t(`trends.${rec.trend}`) }}</span>
                </td>
                <td class="num">{{ rec.quantity.toLocaleString() }}</td>
                <td class="num">{{ formatMoney(rec.unitCost, 2) }}</td>
                <td class="num"><strong>{{ formatMoney(rec.lineTotal, 2) }}</strong></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import { ref, computed, watch, onMounted } from 'vue'
import { api } from '../api'
import { useI18n } from '../composables/useI18n'
import { formatCurrency, formatCurrencyWithDecimals } from '../utils/currency'

export default {
  name: 'Restocking',
  setup() {
    const { t, currentCurrency, translateProductName } = useI18n()

    const loading = ref(true)
    const error = ref(null)
    const forecasts = ref([])
    const budget = ref(0)
    const submitting = ref(false)
    const successMessage = ref('')
    const submitError = ref('')

    // Amounts are kept in USD internally; formatting converts for JPY display
    const formatMoney = (amount, decimals = 0) => {
      return decimals > 0
        ? formatCurrencyWithDecimals(amount, currentCurrency.value, decimals)
        : formatCurrency(amount, currentCurrency.value)
    }

    // Only items whose forecast exceeds current demand need restocking,
    // ordered by the largest shortfall first
    const candidates = computed(() => {
      return forecasts.value
        .map(f => ({
          sku: f.item_sku,
          name: f.item_name,
          trend: f.trend,
          unitCost: f.unit_cost,
          increase: f.forecasted_demand - f.current_demand
        }))
        .filter(c => c.increase > 0 && c.unitCost > 0)
        .sort((a, b) => b.increase - a.increase)
    })

    // Cost of fully restocking every candidate = upper bound of the slider
    const fullCost = computed(() => {
      return candidates.value.reduce((sum, c) => sum + c.increase * c.unitCost, 0)
    })

    // Coarser step for larger totals so the slider stays usable
    const budgetStep = computed(() => (fullCost.value > 20000 ? 1000 : 100))

    // Round up to a multiple of the step so the full amount is reachable
    const maxBudget = computed(() => {
      return Math.ceil(fullCost.value / budgetStep.value) * budgetStep.value
    })

    // Greedy allocation: largest increase first; if the full quantity does not
    // fit in the remaining budget, buy as many units as affordable (skip if 0)
    // and keep going, since cheaper later items may still fit.
    const recommendations = computed(() => {
      let remaining = budget.value
      const result = []
      for (const c of candidates.value) {
        let quantity = c.increase
        if (quantity * c.unitCost > remaining) {
          quantity = Math.floor(remaining / c.unitCost)
        }
        if (quantity <= 0) continue
        const lineTotal = quantity * c.unitCost
        remaining -= lineTotal
        result.push({ ...c, quantity, lineTotal })
      }
      return result
    })

    const totalSpend = computed(() => {
      return recommendations.value.reduce((sum, r) => sum + r.lineTotal, 0)
    })

    const remainingBudget = computed(() => Math.max(0, budget.value - totalSpend.value))

    const loadForecasts = async () => {
      try {
        loading.value = true
        error.value = null
        forecasts.value = await api.getDemandForecasts()
        // Default to roughly half of the maximum, aligned to the slider step
        budget.value = Math.round(maxBudget.value / 2 / budgetStep.value) * budgetStep.value
      } catch (err) {
        error.value = t('restocking.loadError') + ': ' + err.message
      } finally {
        loading.value = false
      }
    }

    const placeOrder = async () => {
      if (recommendations.value.length === 0 || submitting.value) return
      submitting.value = true
      successMessage.value = ''
      submitError.value = ''
      try {
        const order = await api.createRestockingOrder({
          items: recommendations.value.map(r => ({ sku: r.sku, quantity: r.quantity }))
        })
        successMessage.value = t('restocking.orderSuccess', {
          orderNumber: order.order_number,
          days: order.lead_time_days
        })
      } catch (err) {
        console.error('Restocking order failed:', err)
        submitError.value = t('restocking.orderError')
      } finally {
        submitting.value = false
      }
    }

    // Stale result messages no longer apply once the plan changes
    watch(budget, () => {
      successMessage.value = ''
      submitError.value = ''
    })

    onMounted(loadForecasts)

    return {
      t,
      translateProductName,
      loading,
      error,
      budget,
      budgetStep,
      maxBudget,
      recommendations,
      totalSpend,
      remainingBudget,
      submitting,
      successMessage,
      submitError,
      formatMoney,
      placeOrder
    }
  }
}
</script>

<style scoped>
.budget-card {
  padding: 1.5rem;
}

.budget-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 1rem;
}

.budget-label {
  font-size: 0.875rem;
  font-weight: 600;
  color: #64748b;
}

.budget-value {
  font-size: 1.5rem;
  font-weight: 700;
  color: #0f172a;
}

.budget-slider {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  border-radius: 3px;
  background: #e2e8f0;
  outline: none;
  cursor: pointer;
}

.budget-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #0f172a;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.4);
}

.budget-slider::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #0f172a;
  border: 2px solid white;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.4);
}

.budget-slider:focus-visible {
  outline: 2px solid #64748b;
  outline-offset: 4px;
}

.budget-scale {
  display: flex;
  justify-content: space-between;
  margin-top: 0.5rem;
  font-size: 0.75rem;
  color: #64748b;
}

.place-order-btn {
  padding: 0.5rem 1.25rem;
  background: #0f172a;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
}

.place-order-btn:hover:not(:disabled) {
  background: #1e293b;
}

.place-order-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.message {
  margin-bottom: 1rem;
  padding: 0.75rem 1rem;
  border-radius: 6px;
  font-size: 0.875rem;
}

.success-message {
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #166534;
}

.error-message {
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
}

.empty-state {
  padding: 2rem;
  text-align: center;
  color: #64748b;
}

.num {
  text-align: right;
}
</style>
