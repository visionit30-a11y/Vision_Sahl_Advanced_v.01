import { useEffect, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';

import { Icon } from '../Icon/Icon';
import type { IconName } from '../Icon/Icon';
import styles from './Menu.module.css';

export interface MenuItem {
  id: string;
  label: string;
  icon?: IconName;
  selected?: boolean;
  disabled?: boolean;
  onSelect: () => void;
}

export interface MenuProps {
  label: string;
  items: MenuItem[];
  icon?: IconName;
  iconOnly?: boolean;
  onHeader?: boolean;
  align?: 'start' | 'end';
}

export function Menu({
  label,
  items,
  icon,
  iconOnly = false,
  onHeader = false,
  align = 'end',
}: MenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const itemRefs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (!open) {
      return;
    }

    const handlePointerDown = (event: globalThis.MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener('mousedown', handlePointerDown);
    return () => {
      document.removeEventListener('mousedown', handlePointerDown);
    };
  }, [open]);

  useEffect(() => {
    if (open) {
      itemRefs.current[0]?.focus();
    }
  }, [open]);

  const close = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  const handleListKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.stopPropagation();
      close();
      return;
    }

    if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') {
      return;
    }

    event.preventDefault();
    const buttons = itemRefs.current.filter((item): item is HTMLButtonElement => item !== null);
    if (buttons.length === 0) {
      return;
    }

    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const step = event.key === 'ArrowDown' ? 1 : -1;
    const next = (current + step + buttons.length) % buttons.length;
    buttons[next]?.focus();
  };

  const triggerClass = iconOnly
    ? [styles.triggerIcon, onHeader ? styles.onHeader : styles.onSurface].join(' ')
    : styles.triggerButton;

  return (
    <div className={styles.menu} ref={rootRef}>
      <button
        type="button"
        ref={triggerRef}
        className={triggerClass}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={iconOnly ? label : undefined}
        title={iconOnly ? label : undefined}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        {icon ? <Icon name={icon} size={iconOnly ? 'md' : 'sm'} /> : null}
        {iconOnly ? null : <span>{label}</span>}
        {iconOnly ? null : <Icon name="chevronDown" size="sm" />}
      </button>

      {open ? (
        <div
          className={[styles.list, align === 'start' ? styles.alignStart : styles.alignEnd].join(
            ' ',
          )}
          role="menu"
          aria-label={label}
          onKeyDown={handleListKeyDown}
        >
          {items.map((item, index) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              disabled={item.disabled}
              className={[styles.item, item.selected ? styles.selected : '']
                .filter(Boolean)
                .join(' ')}
              ref={(element) => {
                itemRefs.current[index] = element;
              }}
              onClick={() => {
                item.onSelect();
                close();
              }}
            >
              {item.icon ? <Icon name={item.icon} size="sm" /> : null}
              <span className={styles.itemLabel}>{item.label}</span>
              {item.selected ? <Icon name="check" size="sm" /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
