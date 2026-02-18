'use client';

import { useState } from 'react';
import { Info } from 'lucide-react';

export default function Tooltip({ text }: { text: string }) {
  const [show, setShow] = useState(false);

  return (
    <span className="relative inline-flex ml-1.5 align-middle">
      <Info
        className="w-3.5 h-3.5 text-vm-text-dim hover:text-vm-accent cursor-help transition-colors"
        onMouseEnter={() => setShow(true)}
        onMouseLeave={() => setShow(false)}
      />
      {show && (
        <div className="absolute z-[9999] bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-[#1a2233] border border-vm-border-bright rounded shadow-2xl text-xs text-vm-text font-normal normal-case tracking-normal whitespace-normal w-56 leading-relaxed pointer-events-none">
          {text}
          <div className="absolute top-full left-1/2 -translate-x-1/2 -mt-px w-2 h-2 bg-[#1a2233] border-r border-b border-vm-border-bright rotate-45" />
        </div>
      )}
    </span>
  );
}
