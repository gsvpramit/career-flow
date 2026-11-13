import { useEffect, useMemo, useRef, useState } from "react";

export interface DropdownOptionItem {
  value: string;
  label: string;
  badge?: string;
  subtitle?: string;
  searchText?: string;
}

export interface DropdownOptionGroup {
  title: string;
  items: DropdownOptionItem[];
}

export interface QuickActionItem {
  label: string;
  active?: boolean;
  onClick: () => void;
}

interface MultiSelectCheckboxDropdownProps {
  label?: string;
  summaryText: string;
  groups: DropdownOptionGroup[];
  selected: string[];
  onChange: (next: string[]) => void;
  searchable?: boolean;
  searchPlaceholder?: string;
  quickActions?: QuickActionItem[];
  disabled?: boolean;
}

export function MultiSelectCheckboxDropdown({
  label,
  summaryText,
  groups,
  selected,
  onChange,
  searchable = true,
  searchPlaceholder = "Filter options...",
  quickActions = [],
  disabled = false,
}: MultiSelectCheckboxDropdownProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const handleOutside = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, [open]);

  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((g) => ({
        ...g,
        items: g.items.filter(
          (item) =>
            item.label.toLowerCase().includes(q) ||
            item.value.toLowerCase().includes(q) ||
            (item.badge && item.badge.toLowerCase().includes(q)) ||
            (item.subtitle && item.subtitle.toLowerCase().includes(q)) ||
            (item.searchText && item.searchText.toLowerCase().includes(q))
        ),
      }))
      .filter((g) => g.items.length > 0);
  }, [groups, query]);

  const toggleValue = (val: string) => {
    if (selected.includes(val)) {
      onChange(selected.filter((s) => s !== val));
    } else {
      onChange([...selected, val]);
    }
  };

  return (
    <div className="dropdown-anchor" ref={containerRef}>
      {label && <label>{label}</label>}
      <button
        type="button"
        className={`dropdown-trigger ${open ? "open" : ""}`}
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
      >
        <span className="dropdown-trigger-text">{summaryText}</span>
        <span className="dropdown-caret">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="dropdown-popover">
          {searchable && (
            <input
              type="text"
              className="dropdown-search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={searchPlaceholder}
              autoFocus
            />
          )}

          {quickActions.length > 0 && (
            <div className="dropdown-quick-row">
              {quickActions.map((act) => (
                <button
                  key={act.label}
                  type="button"
                  className={`chip ${act.active ? "selected" : ""}`}
                  onClick={act.onClick}
                >
                  {act.label}
                </button>
              ))}
            </div>
          )}

          <div className="dropdown-scroll">
            {filteredGroups.length === 0 ? (
              <div className="small-note" style={{ padding: "8px 4px" }}>
                No matches for "{query}".
              </div>
            ) : (
              filteredGroups.map((group) => (
                <div key={group.title} className="dropdown-group">
                  <div className="dropdown-group-label">{group.title}</div>
                  {group.items.map((item) => {
                    const checked = selected.includes(item.value);
                    return (
                      <label
                        key={item.value}
                        className={`checkbox-row ${checked ? "checked" : ""}`}
                        style={item.subtitle ? { alignItems: "flex-start" } : undefined}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleValue(item.value)}
                          style={item.subtitle ? { marginTop: 3 } : undefined}
                        />
                        {item.subtitle ? (
                          <div className="checkbox-row-content">
                            <div className="checkbox-row-top">
                              <span className="checkbox-row-label">{item.label}</span>
                              {item.badge && (
                                <span className="pill pill-blue mono">{item.badge}</span>
                              )}
                            </div>
                            <span className="checkbox-row-subtitle" title={item.subtitle}>
                              {item.subtitle}
                            </span>
                          </div>
                        ) : (
                          <>
                            <span className="checkbox-row-label">{item.label}</span>
                            {item.badge && <span className="pill">{item.badge}</span>}
                          </>
                        )}
                      </label>
                    );
                  })}
                </div>
              ))
            )}
          </div>

          <div className="dropdown-footer">
            <span className="small-note">{selected.length} selected</span>
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => setOpen(false)}
            >
              Done
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
