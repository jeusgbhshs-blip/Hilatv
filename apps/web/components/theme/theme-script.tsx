import { THEME_SCRIPT } from "@/lib/theme";

/** Sets <html data-theme> before first paint so there is no flash (DESIGN.md §4.2). */
export function ThemeScript() {
  return <script id="hilatv-theme-script" dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />;
}
