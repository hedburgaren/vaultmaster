'use client';

import { useState, useEffect } from 'react';
import { Clock, ChevronDown } from 'lucide-react';

interface CronBuilderProps {
  value: string;
  onChange: (cron: string) => void;
}

const PRESETS = [
  { label: 'Every hour', cron: '0 * * * *', desc: 'At minute 0 of every hour' },
  { label: 'Every 6 hours', cron: '0 */6 * * *', desc: 'At minute 0 every 6 hours' },
  { label: 'Daily at 03:00', cron: '0 3 * * *', desc: 'Every day at 3:00 AM' },
  { label: 'Daily at midnight', cron: '0 0 * * *', desc: 'Every day at midnight' },
  { label: 'Twice daily', cron: '0 3,15 * * *', desc: 'Every day at 3:00 AM and 3:00 PM' },
  { label: 'Weekly (Sun 03:00)', cron: '0 3 * * 0', desc: 'Every Sunday at 3:00 AM' },
  { label: 'Weekly (Mon 03:00)', cron: '0 3 * * 1', desc: 'Every Monday at 3:00 AM' },
  { label: 'Monthly (1st, 03:00)', cron: '0 3 1 * *', desc: '1st of every month at 3:00 AM' },
  { label: 'Quarterly', cron: '0 3 1 */3 *', desc: '1st of every 3rd month at 3:00 AM' },
];

function describeCron(cron: string): string {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return 'Invalid cron expression';

  const [min, hour, dom, month, dow] = parts;
  const preset = PRESETS.find(p => p.cron === cron);
  if (preset) return preset.desc;

  const pieces: string[] = [];

  if (min === '0' && hour !== '*') {
    if (hour.includes(',')) {
      pieces.push(`At ${hour.split(',').map(h => `${h.padStart(2, '0')}:00`).join(' and ')}`);
    } else if (hour.includes('/')) {
      pieces.push(`Every ${hour.split('/')[1]} hours`);
    } else {
      pieces.push(`At ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`);
    }
  } else if (min === '*' && hour === '*') {
    pieces.push('Every minute');
  } else if (hour === '*') {
    if (min.includes('/')) {
      pieces.push(`Every ${min.split('/')[1]} minutes`);
    } else {
      pieces.push(`At minute ${min} of every hour`);
    }
  } else {
    pieces.push(`At ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`);
  }

  if (dom !== '*') {
    if (dom.includes('/')) pieces.push(`every ${dom.split('/')[1]} days`);
    else pieces.push(`on day ${dom}`);
  }
  if (month !== '*') {
    if (month.includes('/')) pieces.push(`every ${month.split('/')[1]} months`);
    else {
      const months = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      pieces.push(`in ${month.split(',').map(m => months[parseInt(m)] || m).join(', ')}`);
    }
  }
  if (dow !== '*') {
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    pieces.push(`on ${dow.split(',').map(d => days[parseInt(d)] || d).join(', ')}`);
  }

  return pieces.join(' ') || 'Custom schedule';
}

export default function CronBuilder({ value, onChange }: CronBuilderProps) {
  const [showPresets, setShowPresets] = useState(false);
  const [mode, setMode] = useState<'preset' | 'custom'>(
    PRESETS.some(p => p.cron === value) ? 'preset' : 'custom'
  );

  const description = describeCron(value);

  return (
    <div className="space-y-2">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => setMode('preset')}
          className={`px-3 py-1 rounded text-[10px] font-bold tracking-wider uppercase transition-all ${mode === 'preset' ? 'bg-vm-accent text-vm-bg' : 'bg-vm-surface2 text-vm-text-dim border border-vm-border hover:border-vm-accent'}`}
        >
          Presets
        </button>
        <button
          type="button"
          onClick={() => setMode('custom')}
          className={`px-3 py-1 rounded text-[10px] font-bold tracking-wider uppercase transition-all ${mode === 'custom' ? 'bg-vm-accent text-vm-bg' : 'bg-vm-surface2 text-vm-text-dim border border-vm-border hover:border-vm-accent'}`}
        >
          Custom
        </button>
      </div>

      {mode === 'preset' ? (
        <div className="relative">
          <button
            type="button"
            onClick={() => setShowPresets(!showPresets)}
            className="w-full flex items-center justify-between bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none hover:border-vm-accent transition-colors"
          >
            <span>{PRESETS.find(p => p.cron === value)?.label || 'Select schedule...'}</span>
            <ChevronDown className={`w-4 h-4 text-vm-text-dim transition-transform ${showPresets ? 'rotate-180' : ''}`} />
          </button>
          {showPresets && (
            <div className="absolute z-40 top-full left-0 right-0 mt-1 bg-vm-surface2 border border-vm-border-bright rounded shadow-lg max-h-60 overflow-y-auto">
              {PRESETS.map(p => (
                <button
                  key={p.cron}
                  type="button"
                  onClick={() => { onChange(p.cron); setShowPresets(false); }}
                  className={`w-full text-left px-3 py-2.5 hover:bg-vm-accent/10 transition-colors ${value === p.cron ? 'bg-vm-accent/10 text-vm-accent' : ''}`}
                >
                  <div className="font-mono text-sm font-semibold">{p.label}</div>
                  <div className="font-mono text-[10px] text-vm-text-dim">{p.cron} — {p.desc}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <input
          value={value}
          onChange={e => onChange(e.target.value)}
          className="w-full bg-vm-surface2 border border-vm-border rounded px-3 py-2.5 text-vm-text font-mono text-sm outline-none focus:border-vm-accent"
          placeholder="0 3 * * *"
          spellCheck={false}
        />
      )}

      <div className="flex items-center gap-2 px-2 py-1.5 bg-vm-accent/[0.05] border border-vm-accent/20 rounded">
        <Clock className="w-3.5 h-3.5 text-vm-accent shrink-0" />
        <span className="font-mono text-[11px] text-vm-accent">{description}</span>
      </div>
    </div>
  );
}
