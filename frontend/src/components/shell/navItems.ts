import { LayoutGrid, ListTree, Server, Workflow, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutGrid, end: true },
  { to: "/workflows", label: "Workflows", icon: Workflow },
  { to: "/runs", label: "Runs", icon: ListTree },
  { to: "/workers", label: "Workers", icon: Server },
];
