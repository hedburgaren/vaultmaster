'use client';

import Tooltip from './Tooltip';

interface FormLabelProps {
  label: string;
  tooltip?: string;
}

export default function FormLabel({ label, tooltip }: FormLabelProps) {
  return (
    <label className="block font-mono text-[11px] text-vm-text-dim tracking-[2px] uppercase mb-2">
      {label}
      {tooltip && <Tooltip text={tooltip} />}
    </label>
  );
}
