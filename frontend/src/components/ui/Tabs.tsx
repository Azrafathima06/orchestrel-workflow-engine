import { cn } from "@/lib/utils";

interface Tab {
  id: string;
  label: string;
}

interface TabsProps {
  tabs: Tab[];
  active: string;
  onChange: (id: string) => void;
}

export function Tabs({ tabs, active, onChange }: TabsProps) {
  return (
    <div className="flex items-center gap-1 border-b border-[var(--color-border-subtle)]">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          onClick={() => onChange(tab.id)}
          className={cn(
            "relative px-3 py-2 text-sm font-medium transition-colors",
            active === tab.id
              ? "text-[var(--color-text-primary)]"
              : "text-[var(--color-text-tertiary)] hover:text-[var(--color-text-secondary)]",
          )}
        >
          {tab.label}
          {active === tab.id && (
            <span className="absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-[var(--color-accent)]" />
          )}
        </button>
      ))}
    </div>
  );
}
