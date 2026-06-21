import { useEffect, useState } from 'react';
import NavBar from '../components/NavBar';
import { loadCycles, calculateMetrics } from '../lib/cycles';

export default function Home() {
  const [cycles, setCycles] = useState([]);
  const [summary, setSummary] = useState(null);

  // Load cycles from localStorage when component mounts.
  useEffect(() => {
    const data = loadCycles();
    setCycles(data);
  }, []);

  // Compute summary for the latest cycle whenever cycles change.
  useEffect(() => {
    if (cycles.length === 0) {
      setSummary(null);
      return;
    }
    const sorted = [...cycles].sort((a, b) => new Date(a.endDate) - new Date(b.endDate));
    const latest = sorted[sorted.length - 1];
    const previous = sorted.length > 1 ? sorted[sorted.length - 2] : null;
    const metrics = calculateMetrics(latest, previous);
    // Determine highest usage category.
    let highestCategory = 'Normal';
    if (latest.peak >= latest.normal && latest.peak >= latest.offPeak) highestCategory = 'Peak';
    if (latest.offPeak >= latest.normal && latest.offPeak >= latest.peak) highestCategory = 'Off-Peak';

    // Determine main reason for increase based on change in each category.
    let reason = '';
    if (previous) {
      const normalChange = latest.normal - previous.normal;
      const peakChange = latest.peak - previous.peak;
      const offChange = latest.offPeak - previous.offPeak;
      const largestIncrease = Math.max(normalChange, peakChange, offChange);
      if (largestIncrease > 0) {
        if (largestIncrease === normalChange) reason = 'Normal load increased';
        else if (largestIncrease === peakChange) reason = 'Peak load increased';
        else reason = 'Off‑peak load increased';
      }
    }

    setSummary({ latest, metrics, highestCategory, reason });
  }, [cycles]);

  return (
    <>
      <NavBar />
      <main>
        <h1>Meter Cost Analyzer</h1>
        {summary ? (
          <div>
            <div className="card">
              <h2>Latest Bill Amount</h2>
              <p>{summary.latest.totalBill.toLocaleString(undefined, { style: 'currency', currency: 'INR' })}</p>
            </div>
            <div className="card">
              <h2>Total Units</h2>
              <p>{summary.metrics.totalUnits}</p>
            </div>
            <div className="card">
              <h2>Highest Usage Category</h2>
              <p>{summary.highestCategory}</p>
            </div>
            {summary.metrics.billChange !== null && (
              <div className="card">
                <h2>Bill Change vs Previous</h2>
                <p>
                  {summary.metrics.billChange >= 0 ? '+' : ''}
                  {summary.metrics.billChange.toLocaleString(undefined, { style: 'currency', currency: 'INR' })}
                </p>
              </div>
            )}
            {summary.metrics.usageChange !== null && (
              <div className="card">
                <h2>Usage Change vs Previous</h2>
                <p>
                  {summary.metrics.usageChange >= 0 ? '+' : ''}
                  {summary.metrics.usageChange} units
                </p>
              </div>
            )}
            {summary.reason && (
              <div className="card">
                <h2>Main Reason</h2>
                <p>{summary.reason}</p>
              </div>
            )}
          </div>
        ) : (
          <p>No cycles recorded yet. Go to the Add Cycle page to add your first billing cycle.</p>
        )}
      </main>
    </>
  );
}
