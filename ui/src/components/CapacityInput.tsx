'use client';

import { useState, useEffect } from 'react';

interface CapacityInputProps {
  value: number | null;
  onChange: (bytes: number | null) => void;
}

const UNITS = [
  { label: 'GB', multiplier: 1024 ** 3 },
  { label: 'TB', multiplier: 1024 ** 4 },
  { label: 'PB', multiplier: 1024 ** 5 },
];

function bytesToHuman(bytes: number | null): { amount: string; unit: string } {
  if (!bytes || bytes === 0) return { amount: '', unit: 'TB' };
  for (let i = UNITS.length - 1; i >= 0; i--) {
    if (bytes >= UNITS[i].multiplier) {
      const val = bytes / UNITS[i].multiplier;
      return { amount: val % 1 === 0 ? val.toString() : val.toFixed(1), unit: UNITS[i].label };
    }
  }
  return { amount: (bytes / UNITS[0].multiplier).toFixed(1), unit: 'GB' };
}

export default function CapacityInput({ value, onChange }: CapacityInputProps) {
  const initial = bytesToHuman(value);
  const [amount, setAmount] = useState(initial.amount);
  const [unit, setUnit] = useState(initial.unit);

  useEffect(() => {
    const num = parseFloat(amount);
    if (isNaN(num) || num <= 0) {
      onChange(null);
      return;
    }
    const multiplier = UNITS.find(u => u.label === unit)?.multiplier || UNITS[1].multiplier;
    onChange(Math.round(num * multiplier));
  }, [amount, unit]);

  return (
    <div className="flex gap-2">
      <input
        type="number"
        value={amount}
        onChange={e => setAmount(e.target.value)}
        placeholder="2"
        min="0"
        step="0.1"
        className="flex-1 bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent"
      />
      <select
        value={unit}
        onChange={e => setUnit(e.target.value)}
        className="bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent w-20"
      >
        {UNITS.map(u => (
          <option key={u.label} value={u.label}>{u.label}</option>
        ))}
      </select>
    </div>
  );
}
