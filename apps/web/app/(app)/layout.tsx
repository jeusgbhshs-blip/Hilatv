import { AppShell } from "@/components/hilatv/app-shell";

/** Application shell: sidebar, top bar with the five-step stepper, phone tab bar (DESIGN.md §8.2). */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
