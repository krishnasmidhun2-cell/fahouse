import { useState, useEffect } from 'react';
import NavBar from '../components/NavBar';
import { loadCycles, calculateMetrics } from '../lib/cycles';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
} from 'chart.js';
import { Bar, Line, Doughnut } from 'react-chartjs-2';

// Register Chart.js components once
ChartJS.register(
  CategoryScale,
  LinearScale,
  BarElement,
  PointElement,
  LineElement,
  ArcElement,
  Title,
  Tooltip,
  Legend
);

export default function Graphs() {
  const [cycles, setCycles] = useState([]);
  const [selectedChart, setSelectedChart] = useState('billTrend');
  const [reduction, setReduction] = useState({ normal: 0, peak: 0, offPeak: 0 });
  const [estimatedBill, setEstimatedBill] = useState(null);

  useEffect(() => {
    const data = loadCycles();
    // Sort cycles chronologically
    const sorted = data.sort((a, b) => new Date(a.startDate) - new Date(b.startDate));
    setCycles(sorted);
  }, []);

  // Helper to generate labels
  const cycleLabels = cycles.map((c) => {
    const start = new Date(c.startDate).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
    const end = new Date(c.endDate).toLocaleDateString('en-GB', { day: '2-digit', month: 'short' });
    return `${start} - ${end}`;
  });

  // Data for Bill Trend line chart
  const billTrendData = {
    labels: cycleLabels,
    datasets: [
      {
        label: 'Total Bill',
        data: cycles.map((c) => c.totalBill),
        fill: false,
        borderColor: '#0070f3',
        backgroundColor: '#0070f3'
      }
    ]
  };

  // Data for Usage Trend line chart (multiple lines)
  const usageTrendData = {
    labels: cycleLabels,
    datasets: [
      {
        label: 'Normal',
        data: cycles.map((c) => c.normal),
        fill: false,
        borderColor: '#1c7ed6',
        backgroundColor: '#1c7ed6'
      },
      {
        label: 'Peak',
        data: cycles.map((c) => c.peak),
        fill: false,
        borderColor: '#e8590c',
        backgroundColor: '#e8590c'
      },
      {
        label: 'Off‑Peak',
        data: cycles.map((c) => c.offPeak),
        fill: false,
        borderColor: '#2b8a3e',
        backgroundColor: '#2b8a3e'
      }
    ]
  };

  // Data for Load Share stacked bar chart
  const loadShareData = {
    labels: cycleLabels,
    datasets: [
      {
        label: 'Normal',
        data: cycles.map((c) => c.normal),
        backgroundColor: '#1c7ed6'
      },
      {
        label: 'Peak',
        data: cycles.map((c) => c.peak),
        backgroundColor: '#e8590c'
      },
      {
        label: 'Off‑Peak',
        data: cycles.map((c) => c.offPeak),
        backgroundColor: '#2b8a3e'
      }
    ]
  };

  const loadShareOptions = {
    plugins: { legend: { position: 'top' }, title: { display: true, text: 'Load Share per Cycle (stacked)' } },
    responsive: true,
    scales: {
      x: { stacked: true },
      y: { stacked: true, beginAtZero: true }
    }
  };

  // Data for Load Share Pie chart (latest cycle)
  const latest = cycles.length > 0 ? cycles[cycles.length - 1] : null;
  const pieData = latest
    ? {
        labels: ['Normal', 'Peak', 'Off‑Peak'],
        datasets: [
          {
            data: [latest.normal, latest.peak, latest.offPeak],
            backgroundColor: ['#1c7ed6', '#e8590c', '#2b8a3e']
          }
        ]
      }
    : null;

  // Data for Comparison bar chart (latest vs previous)
  const comparisonData = latest && cycles.length > 1
    ? {
        labels: ['Normal', 'Peak', 'Off‑Peak'],
        datasets: [
          {
            label: 'Latest',
            data: [latest.normal, latest.peak, latest.offPeak],
            backgroundColor: '#0070f3'
          },
          {
            label: 'Previous',
            data: [cycles[cycles.length - 2].normal, cycles[cycles.length - 2].peak, cycles[cycles.length - 2].offPeak],
            backgroundColor: '#888'
          }
        ]
      }
    : null;

  // Data for Cost Impact chart (usage change vs bill change)
  const costImpactData = latest && cycles.length > 1
    ? (() => {
        const prev = cycles[cycles.length - 2];
        const diffNormal = latest.normal - prev.normal;
        const diffPeak = latest.peak - prev.peak;
        const diffOff = latest.offPeak - prev.offPeak;
        return {
          labels: ['Normal Δ', 'Peak Δ', 'Off‑Peak Δ'],
          datasets: [
            {
              label: 'Change in units',
              data: [diffNormal, diffPeak, diffOff],
              backgroundColor: ['#1c7ed6', '#e8590c', '#2b8a3e']
            }
          ]
        };
      })()
    : null;

  // Reduction simulator: compute estimated new bill
  useEffect(() => {
    if (!latest) {
      setEstimatedBill(null);
      return;
    }
    const totalUnits = latest.normal + latest.peak + latest.offPeak;
    if (totalUnits === 0) {
      setEstimatedBill(latest.totalBill);
      return;
    }
    const averageRate = latest.totalBill / totalUnits;
    const reducedNormal = latest.normal * (1 - reduction.normal / 100);
    const reducedPeak = latest.peak * (1 - reduction.peak / 100);
    const reducedOff = latest.offPeak * (1 - reduction.offPeak / 100);
    const newUnits = reducedNormal + reducedPeak + reducedOff;
    const newBill = newUnits * averageRate;
    setEstimatedBill(Math.round(newBill * 100) / 100);
  }, [reduction, latest]);

  // Handler for reduction input
  const handleReductionChange = (field, value) => {
    setReduction((prev) => ({ ...prev, [field]: Number(value) }));
  };

  return (
    <>
      <NavBar />
      <main>
        <h1>Graphs & Analysis</h1>
        {cycles.length === 0 ? (
          <p>No data available. Add cycles first.</p>
        ) : (
          <>
            <div style={{ marginBottom: '1rem' }}>
              <button onClick={() => setSelectedChart('billTrend')}>Bill Trend</button>{' '}
              <button onClick={() => setSelectedChart('usageTrend')}>Usage Trend</button>{' '}
              <button onClick={() => setSelectedChart('loadShare')}>Load Share</button>{' '}
              <button onClick={() => setSelectedChart('pie')}>Latest Share</button>{' '}
              <button onClick={() => setSelectedChart('comparison')}>Current vs Previous</button>{' '}
              <button onClick={() => setSelectedChart('costImpact')}>Change Impact</button>{' '}
              <button onClick={() => setSelectedChart('reduction')}>Reduction Simulator</button>
            </div>
            {selectedChart === 'billTrend' && (
              <div className="card">
                <Line data={billTrendData} options={{ plugins: { title: { display: true, text: 'Bill Trend Across Cycles' } }, responsive: true }} />
              </div>
            )}
            {selectedChart === 'usageTrend' && (
              <div className="card">
                <Line data={usageTrendData} options={{ plugins: { title: { display: true, text: 'Usage Trend Across Cycles' } }, responsive: true }} />
              </div>
            )}
            {selectedChart === 'loadShare' && (
              <div className="card">
                <Bar data={loadShareData} options={loadShareOptions} />
              </div>
            )}
            {selectedChart === 'pie' && pieData && (
              <div className="card">
                <Doughnut data={pieData} options={{ plugins: { title: { display: true, text: 'Latest Cycle Load Share' } }, responsive: true }} />
              </div>
            )}
            {selectedChart === 'comparison' && comparisonData && (
              <div className="card">
                <Bar data={comparisonData} options={{ plugins: { title: { display: true, text: 'Current vs Previous Cycle' } }, responsive: true }} />
              </div>
            )}
            {selectedChart === 'costImpact' && costImpactData && (
              <div className="card">
                <Bar data={costImpactData} options={{ plugins: { title: { display: true, text: 'Change in Usage per Category' } }, responsive: true }} />
              </div>
            )}
            {selectedChart === 'reduction' && (
              <div className="card">
                <h2>Reduction Simulator</h2>
                <p>Estimate your bill if you reduce usage:</p>
                <div>
                  <label>
                    Normal Load Reduction (%):
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={reduction.normal}
                      onChange={(e) => handleReductionChange('normal', e.target.value)}
                    />
                  </label>
                </div>
                <div>
                  <label>
                    Peak Load Reduction (%):
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={reduction.peak}
                      onChange={(e) => handleReductionChange('peak', e.target.value)}
                    />
                  </label>
                </div>
                <div>
                  <label>
                    Off‑Peak Load Reduction (%):
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={reduction.offPeak}
                      onChange={(e) => handleReductionChange('offPeak', e.target.value)}
                    />
                  </label>
                </div>
                {estimatedBill !== null && (
                  <p>
                    Estimated new bill: {estimatedBill.toLocaleString(undefined, { style: 'currency', currency: 'INR' })}
                  </p>
                )}
                <small>
                  This estimate uses the average rate of the latest cycle. Exact savings may vary depending on fixed charges
                  and slabs.
                </small>
              </div>
            )}
          </>
        )}
      </main>
    </>
  );
}
