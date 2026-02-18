'use client';

import { useState, useRef, useEffect } from 'react';
import { X } from 'lucide-react';

interface TagInputProps {
  value: string[];
  onChange: (tags: string[]) => void;
  suggestions?: string[];
  placeholder?: string;
}

export default function TagInput({ value, onChange, suggestions = [], placeholder = 'Add tag...' }: TagInputProps) {
  const [input, setInput] = useState('');
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  const filtered = suggestions.filter(
    s => s.toLowerCase().includes(input.toLowerCase()) && !value.includes(s)
  );

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setShowSuggestions(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const addTag = (tag: string) => {
    const t = tag.trim().toLowerCase();
    if (t && !value.includes(t)) {
      onChange([...value, t]);
    }
    setInput('');
    setShowSuggestions(false);
    inputRef.current?.focus();
  };

  const removeTag = (tag: string) => {
    onChange(value.filter(t => t !== tag));
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.key === 'Enter' || e.key === ',') && input.trim()) {
      e.preventDefault();
      addTag(input);
    }
    if (e.key === 'Backspace' && !input && value.length > 0) {
      removeTag(value[value.length - 1]);
    }
  };

  return (
    <div ref={wrapperRef} className="relative">
      <div className="flex flex-wrap gap-1.5 bg-vm-surface2 border border-vm-border rounded px-2.5 py-2 min-h-[42px] focus-within:border-vm-accent transition-colors">
        {value.map(tag => (
          <span key={tag} className="inline-flex items-center gap-1 px-2.5 py-0.5 bg-vm-accent/10 border border-vm-accent/30 rounded-sm font-mono text-[10px] text-vm-accent uppercase tracking-wider">
            {tag}
            <button onClick={() => removeTag(tag)} className="hover:text-vm-danger transition-colors">
              <X className="w-3 h-3" />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          value={input}
          onChange={e => { setInput(e.target.value); setShowSuggestions(true); }}
          onFocus={() => setShowSuggestions(true)}
          onKeyDown={handleKeyDown}
          placeholder={value.length === 0 ? placeholder : ''}
          className="flex-1 min-w-[100px] bg-transparent text-vm-text font-mono text-sm outline-none"
        />
      </div>
      {showSuggestions && filtered.length > 0 && (
        <div className="absolute z-40 top-full left-0 right-0 mt-1 bg-vm-surface2 border border-vm-border-bright rounded shadow-lg max-h-40 overflow-y-auto">
          {filtered.map(s => (
            <button
              key={s}
              onClick={() => addTag(s)}
              className="w-full text-left px-3 py-2 font-mono text-sm text-vm-text hover:bg-vm-accent/10 hover:text-vm-accent transition-colors"
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
