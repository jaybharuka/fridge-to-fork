'use client';
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { useAutocomplete } from '@/hooks/useAutocomplete';
import styles from './landing.module.css';

interface DishInputProps {
  value: string;
  onChange: (value: string) => void;
}

function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

// Splits `text` around case-insensitive matches of `query`, returning React
// children instead of the old dangerouslySetInnerHTML string build —
// templates/index.html:4362-4375 (renderSuggestions/escapeRegExp).
function highlightMatch(text: string, query: string): ReactNode[] {
  if (!query) return [text];
  const regex = new RegExp(`(${escapeRegExp(query)})`, 'gi');
  // A capturing group in the split pattern keeps the matched delimiters in
  // the result, alternating [non-match, match, non-match, match, ...] — so
  // odd indices are always the matched substrings.
  const parts = text.split(regex);
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <span key={i} className={styles.suggestionMatch}>
        {part}
      </span>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

// Ported from templates/index.html:1789 (input) and the suggestion-dropdown
// script block (lines ~4340-4466). Uses useAutocomplete (Task 4) for the
// filtered list instead of the old global INSTANT_DISHES scan.
export function DishInput({ value, onChange }: DishInputProps) {
  const { suggestions, activeIndex, setActiveIndex } = useAutocomplete(value);
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Reopen (or close, if the query no longer matches) whenever the
  // suggestion list itself changes — i.e. whenever the query text changes.
  useEffect(() => {
    setOpen(suggestions.length > 0);
    setActiveIndex(-1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestions]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('click', handleClickOutside);
    return () => document.removeEventListener('click', handleClickOutside);
  }, []);

  function selectSuggestion(dish: string) {
    onChange(dish);
    setOpen(false);
    setActiveIndex(-1);
    inputRef.current?.focus();
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (!open || suggestions.length === 0) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIndex(activeIndex + 1 >= suggestions.length ? 0 : activeIndex + 1);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIndex(activeIndex - 1 < 0 ? suggestions.length - 1 : activeIndex - 1);
    } else if (e.key === 'Enter' && activeIndex >= 0) {
      e.preventDefault();
      selectSuggestion(suggestions[activeIndex]);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  return (
    <div className={styles.inputSection} ref={wrapperRef}>
      <input
        ref={inputRef}
        type="text"
        className={styles.dishInput}
        placeholder='Try "Paneer Tikka" or "Matar Pulao"'
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
      />
      {open && suggestions.length > 0 && (
        <div className={styles.suggestionBox}>
          {suggestions.map((s, i) => (
            <div
              key={s}
              className={`${styles.suggestionRow} ${i === activeIndex ? styles.active : ''}`}
              onMouseEnter={() => setActiveIndex(i)}
              onClick={() => selectSuggestion(s)}
            >
              {highlightMatch(s, value.trim())}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
