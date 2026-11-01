"use client";

import {
  BookMarked,
  ChevronLeft,
  CircleUser,
  FolderOpen,
  GraduationCap,
  Home,
  Images,
  Layers,
  LayoutTemplate,
  type LucideIcon,
  Menu,
  Plus,
  ReceiptText,
  Sparkles,
  SunMoon,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { BrandMark } from "@/components/hilatv/brand-mark";
import { SessionChip } from "@/components/hilatv/session-chip";
import { ShellStageProvider, useShellStageValue } from "@/components/hilatv/shell-stage";
import { StageStepper } from "@/components/hilatv/stage-stepper";
import { cn } from "@/lib/utils";

type NavItem = {
  label: string;
  icon: LucideIcon;
  href?: string;
  match?: (path: string) => boolean;
};

const SOON = "即将开放";

function items(): NavItem[] {
  return [
    { label: "首页", icon: Home, href: "/", match: (value) => value === "/" },
    {
      label: "项目",
      icon: FolderOpen,
      href: "/projects",
      match: (value) =>
        value === "/projects" || (value.startsWith("/projects/") && !value.includes("/expert")),
    },
    { label: "素材库", icon: Images, href: "/assets", match: (value) => value.startsWith("/assets") },
    { label: "模板", icon: LayoutTemplate, href: "/templates", match: (value) => value.startsWith("/templates") },
    { label: "学院", icon: GraduationCap, href: "/academy", match: (value) => value.startsWith("/academy") },
    { label: "方案", icon: Layers, href: "/concepts", match: (value) => value.startsWith("/concepts") },
    { label: "品牌资料", icon: BookMarked, href: "/brand", match: (value) => value.startsWith("/brand") },
    {
      label: "外观",
      icon: SunMoon,
      href: "/settings/appearance",
      match: (value) => value.startsWith("/settings/appearance"),
    },
    {
      label: "用量与账单",
      icon: ReceiptText,
      href: "/usage",
      match: (value) => value.startsWith("/usage"),
    },
    {
      label: "团队设置",
      icon: Users,
      href: "/settings/team",
      match: (value) => value.startsWith("/settings/team"),
    },
  ];
}

const TABS: NavItem[] = [
  { label: "创作", icon: Sparkles, href: "/", match: (path) => path === "/" || path.startsWith("/concepts") },
  {
    label: "项目",
    icon: FolderOpen,
    href: "/projects",
    match: (path) => path.startsWith("/projects"),
  },
  { label: "素材", icon: Images, href: "/assets", match: (path) => path.startsWith("/assets") },
  {
    label: "我的",
    icon: CircleUser,
    href: "/settings/appearance",
    match: (path) => path.startsWith("/settings"),
  },
];

type Crumb = { label: string; href?: string };

function crumbs(path: string): Crumb[] {
  const project = /^\/projects\/([^/]+)(\/(film|expert))?/.exec(path);
  if (project) {
    const base = `/projects/${project[1]}`;
    const list: Crumb[] = [
      { label: "项目", href: "/projects" },
      { label: "当前项目", href: project[3] ? base : undefined },
    ];
    if (project[3] === "film") list.push({ label: "成片" });
    if (project[3] === "expert") list.push({ label: "专家画布" });
    return list;
  }
  if (path === "/projects") return [{ label: "项目" }];
  if (path.startsWith("/assets")) return [{ label: "素材库" }];
  if (path.startsWith("/templates")) return [{ label: "模板" }];
  if (path.startsWith("/academy")) return [{ label: "学院" }];
  if (path.startsWith("/concepts")) return [{ label: "创作", href: "/" }, { label: "方案" }];
  if (path.startsWith("/brand")) return [{ label: "品牌资料" }];
  if (path.startsWith("/settings/appearance")) return [{ label: "设置" }, { label: "外观" }];
  return [{ label: "创作" }];
}

function backHref(path: string): string | null {
  if (path === "/") return null;
  const project = /^\/projects\/([^/]+)\/(film|expert)/.exec(path);
  if (project) return `/projects/${project[1]}`;
  return "/";
}

export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <ShellStageProvider>
      <ShellFrame>{children}</ShellFrame>
    </ShellStageProvider>
  );
}

function ShellFrame({ children }: { children: React.ReactNode }) {
  const path = usePathname() || "/";
  const stage = useShellStageValue();
  const trail = crumbs(path);
  const back = backHref(path);
  const title = trail[trail.length - 1]?.label ?? "";
  const home = path === "/";
  const nav = items();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-dvh bg-bg text-text-1 md:flex">
      <div className="hidden w-16 shrink-0 border-r border-border bg-surface md:block lg:w-55">
        <aside aria-label="主导航" className="sticky top-0 flex h-dvh flex-col">
          <Link
            href="/"
            aria-label="HiLatv 涌现言源 首页"
            className="flex h-15 items-center gap-2.5 px-4 lg:px-5"
          >
            <BrandMark className="size-7" />
            <span className="hidden min-w-0 flex-col lg:flex">
              <span className="text-h2 font-medium">HiLatv</span>
              <span className="text-micro text-text-3">涌现言源</span>
            </span>
          </Link>
          <div className="px-3 pt-2 lg:px-4">
            <Link
              href="/"
              aria-label="新建创作"
              className="flex h-9 items-center justify-center gap-1.5 rounded-sm border border-border-strong bg-surface text-small font-medium text-text-1 transition-colors duration-fast hover:bg-hover lg:justify-start lg:px-3"
            >
              <Plus aria-hidden="true" className="size-4" />
              <span className="hidden lg:inline">新建创作</span>
            </Link>
          </div>
          <nav className="mt-4 min-h-0 flex-1 overflow-y-auto px-3 lg:px-4">
            <div className="grid gap-0.5">
              {nav.map((item) => (
                <NavEntry key={item.label} item={item} path={path} />
              ))}
            </div>
          </nav>
          <div className="border-t border-border px-4 py-4 text-caption text-text-3 lg:px-5">
            <span className="hidden lg:inline">HiLatv 一句成片</span>
          </div>
        </aside>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex flex-wrap items-center gap-x-2 border-b border-border bg-surface px-4 md:h-15 md:flex-nowrap md:gap-x-3 md:px-6">
          {back ? (
            <Link
              href={back}
              aria-label="返回"
              className="-ml-2 flex size-11 items-center justify-center rounded-sm text-text-2 hover:bg-hover md:hidden"
            >
              <ChevronLeft aria-hidden="true" className="size-5" />
            </Link>
          ) : (
            <BrandMark className="size-6 md:hidden" />
          )}
          <p className="flex h-13 min-w-0 flex-1 items-center truncate text-body font-medium md:hidden">
            {title}
          </p>
          <nav aria-label="位置" className="hidden min-w-0 shrink-0 items-center gap-1.5 text-small md:flex">
            {trail.map((item, index) => (
              <span key={`${item.label}-${index}`} className="flex items-center gap-1.5">
                {index > 0 ? <span className="text-text-3">/</span> : null}
                {item.href ? (
                  <Link href={item.href} className="text-text-2 hover:text-text-1">
                    {item.label}
                  </Link>
                ) : (
                  <span className={index === trail.length - 1 ? "text-text-1" : "text-text-2"}>
                    {item.label}
                  </span>
                )}
              </span>
            ))}
          </nav>
          {stage ? (
            <StageStepper
              stage={stage.stage}
              complete={stage.complete}
              className="order-last w-full pb-2 md:order-none md:flex md:w-auto md:flex-1 md:justify-center md:pb-0"
            />
          ) : (
            <span className="hidden flex-1 md:block" />
          )}
          <SessionChip />
          <Link
            href="/settings/appearance"
            aria-label="外观设置"
            className="flex size-11 items-center justify-center rounded-sm text-text-2 hover:bg-hover md:size-8"
          >
            <SunMoon aria-hidden="true" className="size-4" />
          </Link>
          <button
            type="button"
            className="flex size-11 items-center justify-center rounded-sm text-text-2 hover:bg-hover md:hidden"
            aria-label="全部导航"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            {menuOpen ? <X aria-hidden="true" className="size-5" /> : <Menu aria-hidden="true" className="size-5" />}
          </button>
        </header>
        {menuOpen ? (
          <nav aria-label="全部导航" className="border-b border-border bg-surface px-4 py-2 md:hidden">
            <div className="grid gap-1 py-2">
              {nav.map((item) => (
                <MobileEntry key={item.label} item={item} path={path} onNavigate={() => setMenuOpen(false)} />
              ))}
            </div>
          </nav>
        ) : null}

        <main className={cn("min-w-0 flex-1", home ? "pb-14 md:pb-0" : "px-4 pt-6 pb-24 md:px-6 md:pt-8 md:pb-10")}>
          {children}
        </main>
      </div>

      <nav
        aria-label="底部导航"
        className="fixed inset-x-0 bottom-0 z-10 grid h-14 grid-cols-4 border-t border-border bg-surface md:hidden"
      >
        {TABS.map((item) => {
          const Icon = item.icon;
          const active = item.match?.(path) ?? false;
          return (
            <Link
              key={item.label}
              href={item.href || "/"}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex min-h-11 flex-col items-center justify-center gap-0.5",
                active ? "text-text-1" : "text-text-3",
              )}
            >
              <Icon aria-hidden="true" className="size-5" />
              <span className="text-micro">{item.label}</span>
            </Link>
          );
        })}
      </nav>
    </div>
  );
}

function NavEntry({ item, path }: { item: NavItem; path: string }) {
  const Icon = item.icon;
  const active = item.match?.(path) ?? false;
  const classes = cn(
    "flex h-9 items-center justify-center gap-2.5 rounded-sm text-small lg:justify-start lg:px-3",
    active ? "bg-hover text-text-1" : "text-text-2",
  );
  const body = (
    <>
      <Icon aria-hidden="true" className="size-4 shrink-0" />
      <span className="hidden lg:inline">{item.label}</span>
    </>
  );
  if (!item.href) {
    return (
      <span
        aria-disabled="true"
        title={`${item.label}（${SOON}）`}
        aria-label={`${item.label}（${SOON}）`}
        className={cn(classes, "text-text-disabled")}
      >
        {body}
      </span>
    );
  }
  return (
    <Link
      href={item.href}
      aria-label={item.label}
      aria-current={active ? "page" : undefined}
      className={cn(classes, "transition-colors duration-fast hover:bg-hover hover:text-text-1")}
    >
      {body}
    </Link>
  );
}

function MobileEntry({ item, path, onNavigate }: { item: NavItem; path: string; onNavigate: () => void }) {
  const Icon = item.icon;
  const active = item.match?.(path) ?? false;
  if (!item.href) {
    return (
      <span className="flex min-h-11 items-center gap-2 px-2 text-small text-text-disabled">
        <Icon aria-hidden="true" className="size-4" />
        {item.label}（{SOON}）
      </span>
    );
  }
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={cn(
        "flex min-h-11 items-center gap-2 rounded-sm px-2 text-small",
        active ? "bg-hover text-text-1" : "text-text-2",
      )}
      onClick={onNavigate}
    >
      <Icon aria-hidden="true" className="size-4" />
      {item.label}
    </Link>
  );
}
