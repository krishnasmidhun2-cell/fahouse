import { useState, useEffect } from 'react';
import { useRouter } from 'next/router';
import NavBar from '../components/NavBar';
import { loadCycles, saveCycles } from '../lib/cycles';
import { v4 as uuidv4 } from 'uuid';

// This page provides a form to add or edit a billing cycle.
export default function AddCycle() {
  const router = useRouter();
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [normal, setNormal] = useState('');
  const [peak, setPeak] = useState('');
  const [offPeak, setOffPeak] = useState('');
  const [totalBill, setTotalBill] = useState('');
  const [notes, setNotes] = useState('');

  // Handle form submission
  const handleSubmit = (e) => {
    e.preventDefault();
    // Validate required fields
    if (!startDate || !endDate || normal === '' || peak === '' || offPeak === '' || totalBill === '') {
      alert('Please fill in all fields');
      return;
    }
    const cycle = {
      id: uuidv4(),
      startDate,
      endDate,
      normal: Number(normal),
      peak: Number(peak),
      offPeak: Number(offPeak),
      totalBill: Number(totalBill),
      notes
    };
    const existing = loadCycles();
    existing.push(cycle);
    saveCycles(existing);
    // Redirect to dashboard after saving
    router.push('/');
  };

  return (
    <>
      <NavBar />
      <main>
        <h1>Add Billing Cycle</h1>
        <form onSubmit={handleSubmit}>
          <div className="card">
            <label>Start Date<br />
              <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} required />
            </label>
          </div>
          <div className="card">
            <label>End Date<br />
              <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} required />
            </label>
          </div>
          <div className="card">
            <label>Normal Load Units<br />
              <input type="number" min="0" value={normal} onChange={(e) => setNormal(e.target.value)} required />
            </label>
          </div>
          <div className="card">
            <label>Peak Load Units<br />
              <input type="number" min="0" value={peak} onChange={(e) => setPeak(e.target.value)} required />
            </label>
          </div>
          <div className="card">
            <label>Off‑Peak Load Units<br />
              <input type="number" min="0" value={offPeak} onChange={(e) => setOffPeak(e.target.value)} required />
            </label>
          </div>
          <div className="card">
            <label>Total Bill Amount<br />
              <input type="number" min="0" value={totalBill} onChange={(e) => setTotalBill(e.target.value)} required />
            </label>
          </div>
          <div className="card">
            <label>Notes (optional)<br />
              <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} />
            </label>
          </div>
          <button type="submit">Save Cycle</button>
        </form>
      </main>
    </>
  );
}
