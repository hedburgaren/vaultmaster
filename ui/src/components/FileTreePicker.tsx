'use client';

import { useState } from 'react';
import { browseServer, serverDirSize } from '@/lib/api';
import { formatBytes } from '@/lib/utils';
import { ChevronRight, ChevronDown, Folder, File as FileIcon, Calculator, Loader2 } from 'lucide-react';
import { useT } from '@/lib/i18n';

interface Entry {
  name: string;
  type: string;
  size: number | null;
  modified: string;
}

interface Props {
  serverId: string;
  selected: string[];
  onToggle: (path: string) => void;
  rootPath?: string;
  height?: string;
}

/**
 * Lazy-loading remote directory tree for picking what to back up.
 *
 * One directory is fetched when it is expanded, never the whole disk.
 * Files show their size from the listing; directories get theirs on
 * demand (du -sb on the server), because pre-computing every folder's
 * size would hammer each source host for numbers nobody asked for.
 */
export function FileTreePicker({ serverId, selected, onToggle, rootPath = '/', height = 'h-72' }: Props) {
  const t = useT();
  const [open, setOpen] = useState<Record<string, Entry[]>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<Record<string, string>>({});
  const [dirSizes, setDirSizes] = useState<Record<string, number | '...'>>({});

  const selectedSet = new Set(selected);

  const expand = async (path: string) => {
    if (expanded[path]) {
      setExpanded((e) => ({ ...e, [path]: false }));
      return;
    }
    setExpanded((e) => ({ ...e, [path]: true }));
    if (open[path]) return;
    setLoading((l) => ({ ...l, [path]: true }));
    setError((e) => ({ ...e, [path]: '' }));
    try {
      const res = await browseServer(serverId, path);
      const entries: Entry[] = (res.entries || []).filter(
        (en: any) => !en.error && en.name !== '.' && en.name !== '..',
      );
      entries.sort((a, b) =>
        a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'directory' ? -1 : 1,
      );
      setOpen((o) => ({ ...o, [path]: entries }));
    } catch (e: any) {
      setError((er) => ({ ...er, [path]: e.message || 'kunde inte lista' }));
    } finally {
      setLoading((l) => ({ ...l, [path]: false }));
    }
  };

  const fetchDirSize = async (path: string) => {
    setDirSizes((s) => ({ ...s, [path]: '...' }));
    try {
      const res = await serverDirSize(serverId, path);
      setDirSizes((s) => ({ ...s, [path]: res.bytes }));
    } catch (e: any) {
      setDirSizes((s) => ({ ...s, [path]: -1 }));
    }
  };

  const renderEntries = (path: string, entries: Entry[], depth: number) => {
    if (error[path]) {
      return <div className="font-mono text-[10px] text-vm-danger px-2 py-1">{error[path]}</div>;
    }
    return entries.map((en) => {
      const full = path === '/' ? `/${en.name}` : `${path}/${en.name}`;
      const isDir = en.type === 'directory';
      const isOpen = !!expanded[full];
      return (
        <div key={full}>
          <div
            className={`flex items-center gap-1.5 px-1.5 py-[3px] rounded hover:bg-vm-surface2 ${selectedSet.has(full) ? 'bg-vm-accent/[0.08]' : ''}`}
            style={{ paddingLeft: depth * 14 + 6 }}
          >
            <button
              onClick={() => (isDir ? expand(full) : onToggle(full))}
              className="shrink-0 text-vm-text-dim hover:text-vm-text-bright w-4"
              title={isDir ? '' : t('tree.toggle_file')}
            >
              {isDir ? (isOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />) : <span className="inline-block w-3.5" />}
            </button>
            <input
              type="checkbox"
              checked={selectedSet.has(full)}
              onChange={() => onToggle(full)}
              className="shrink-0 accent-[var(--vm-accent)]"
            />
            {isDir ? <Folder className="w-3.5 h-3.5 text-vm-accent shrink-0" /> : <FileIcon className="w-3.5 h-3.5 text-vm-text-dim shrink-0" />}
            <button
              onClick={() => (isDir ? expand(full) : onToggle(full))}
              className="font-mono text-[11px] text-vm-text truncate text-left flex-1 min-w-0"
              title={full}
            >
              {en.name}
            </button>
            {isDir ? (
              dirSizes[full] === undefined ? (
                <button
                  onClick={() => fetchDirSize(full)}
                  className="shrink-0 text-vm-text-dim hover:text-vm-accent"
                  title={t('tree.calc_size')}
                >
                  <Calculator className="w-3 h-3" />
                </button>
              ) : dirSizes[full] === '...' ? (
                <Loader2 className="w-3 h-3 animate-spin text-vm-accent shrink-0" />
              ) : dirSizes[full] === -1 ? (
                <span className="font-mono text-[10px] text-vm-danger shrink-0">?</span>
              ) : (
                <span className="font-mono text-[10px] text-vm-text-dim shrink-0" title={t('tree.size_on_disk')}>{formatBytes(dirSizes[full] as number)}</span>
              )
            ) : (
              <span className="font-mono text-[10px] text-vm-text-dim shrink-0">{en.size != null ? formatBytes(en.size) : ''}</span>
            )}
            <span className="font-mono text-[9px] text-vm-text-dim/70 shrink-0 hidden md:inline">{en.modified}</span>
          </div>
          {isDir && isOpen && (
            loading[full] ? (
              <div className="font-mono text-[10px] text-vm-text-dim px-2 py-1" style={{ paddingLeft: depth * 14 + 28 }}>
                <Loader2 className="w-3 h-3 animate-spin inline mr-1" />{t('tree.loading')}
              </div>
            ) : (
              open[full] && renderEntries(full, open[full], depth + 1)
            )
          )}
        </div>
      );
    });
  };

  return (
    <div className={`border border-vm-border rounded bg-vm-bg overflow-y-auto ${height}`}>
      <div className="sticky top-0 bg-vm-surface2 border-b border-vm-border px-2 py-1 font-mono text-[10px] uppercase tracking-[2px] text-vm-text-dim">
        {t('tree.pick_hint')}
      </div>
      {renderEntries(rootPath, open[rootPath] || [], 0)}
      {!expanded[rootPath] && (
        <button onClick={() => expand(rootPath)} className="flex items-center gap-1.5 px-2 py-1.5 font-mono text-[11px] text-vm-accent hover:underline">
          <ChevronRight className="w-3.5 h-3.5" />{rootPath}
        </button>
      )}
    </div>
  );
}
