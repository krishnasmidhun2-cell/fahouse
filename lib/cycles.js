// Utility functions for managing cycle data in localStorage and computing summary metrics.

// Each cycle entry has the following shape:
// {
//   id: string,            // unique identifier
//   startDate: string,     // ISO date string
//   endDate: string,       // ISO date string
//   normal: number,        // units during normal load
//   peak: number,          // units during peak load
//   offPeak: number,       // units during off‑peak load
//   totalBill: number,     // total billed amount for the cycle
//   notes?: string         // optional notes
// }

// Load cycles from localStorage. Returns an empty array when none are stored.
export function loadCycles() {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem('cycles');
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch (e) {
    console.error('Failed to parse cycles from localStorage', e);
    return [];
  }
}

// Save cycles array to localStorage.
export function saveCycles(cycles) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem('cycles', JSON.stringify(cycles));
  } catch (e) {
    console.error('Failed to save cycles to localStorage', e);
  }
}

// Calculate derived metrics for a cycle.
export function calculateMetrics(cycle, previousCycle) {
  const totalUnits = cycle.normal + cycle.peak + cycle.offPeak;
  const normalShare = totalUnits > 0 ? (cycle.normal / totalUnits) * 100 : 0;
  const peakShare = totalUnits > 0 ? (cycle.peak / totalUnits) * 100 : 0;
  const offPeakShare = totalUnits > 0 ? (cycle.offPeak / totalUnits) * 100 : 0;
  const averageRate = totalUnits > 0 ? cycle.totalBill / totalUnits : 0;

  // Compare with previous cycle
  let billChange = null;
  let usageChange = null;
  if (previousCycle) {
    const prevUnits = previousCycle.normal + previousCycle.peak + previousCycle.offPeak;
    billChange = cycle.totalBill - previousCycle.totalBill;
    usageChange = totalUnits - prevUnits;
  }

  return {
    totalUnits,
    normalShare,
    peakShare,
    offPeakShare,
    averageRate,
    billChange,
    usageChange
  };
}
