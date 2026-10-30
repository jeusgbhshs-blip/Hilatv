"use client";

import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiUrl, errorMessage } from "@/lib/api";
import { INDUSTRIES } from "@/lib/industries";
import { rememberedEnterprise } from "@/lib/selection";

type Preview = { logo?: string; mono_white?: string; mono_black?: string };

type SavedBrand = {
  brand_kit: {
    company_name: string;
    colors: { primary: string; secondary: string; accent: string };
    fonts: { title: string; body: string };
    cta: { phone: string; website: string };
    products: { name: string; selling_points: string[] }[];
    people: { role: string; consent: boolean }[];
  };
  usable_people: string[];
  previews: Preview;
};

async function asBase64(file: File): Promise<string> {
  const data = await file.arrayBuffer();
  const bytes = new Uint8Array(data);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

export function BrandDesk() {
  const [company, setCompany] = useState("青岛测试机械");
  const [industry, setIndustry] = useState("manufacturing");
  const [logo, setLogo] = useState<File | null>(null);
  const [productName, setProductName] = useState("");
  const [points, setPoints] = useState("");
  const [productPhoto, setProductPhoto] = useState<File | null>(null);
  const [role, setRole] = useState("");
  const [consent, setConsent] = useState(false);
  const [voiceId, setVoiceId] = useState("");
  const [phone, setPhone] = useState("");
  const [website, setWebsite] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<SavedBrand | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!logo) {
      setError("先上传 Logo");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const products = [];
      if (productName.trim()) {
        const photo = productPhoto ?? logo;
        products.push({
          name: productName.trim(),
          photo_b64: await asBase64(photo),
          selling_points: points
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean),
        });
      }
      const people = role.trim()
        ? [{ role: role.trim(), consent, voice_id: consent ? voiceId.trim() || null : null }]
        : [];
      const response = await fetch(apiUrl("/v1/brands"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          enterprise_id: rememberedEnterprise(),
          company_name: company.trim(),
          industry,
          logo_b64: await asBase64(logo),
          products,
          people,
          phone: phone.trim(),
          website: website.trim(),
        }),
      });
      if (!response.ok) throw new Error(await errorMessage(response));
      setSaved((await response.json()) as SavedBrand);
    } catch (caught) {
      setSaved(null);
      setError(caught instanceof Error ? caught.message : "保存没有成功");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,40rem)_18rem]">
      <form className="min-w-0" onSubmit={onSubmit}>
        <p className="text-sm text-muted-foreground">企业后台</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">品牌资料</h1>
        <p className="mt-3 max-w-xl text-base leading-7 text-muted-foreground">
          录入一次。之后新建的项目会自动套用 Logo、色彩、字体、行动号召和卖点。
        </p>

        <div className="mt-8 grid gap-2">
          <Label htmlFor="company">企业名称</Label>
          <Input id="company" value={company} onChange={(event) => setCompany(event.target.value)} />
        </div>

        <fieldset className="mt-6">
          <legend className="text-sm font-medium">行业</legend>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
            {INDUSTRIES.map((item) => (
              <Button
                key={item.id}
                type="button"
                variant={industry === item.id ? "default" : "outline"}
                aria-pressed={industry === item.id}
                onClick={() => setIndustry(item.id)}
              >
                {item.label}
              </Button>
            ))}
          </div>
        </fieldset>

        <div className="mt-6 grid gap-2">
          <Label htmlFor="logo">Logo</Label>
          <Input
            id="logo"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => setLogo(event.target.files?.[0] ?? null)}
          />
        </div>

        <div className="mt-6 grid gap-2">
          <Label htmlFor="product-name">产品名称</Label>
          <Input id="product-name" value={productName} onChange={(event) => setProductName(event.target.value)} />
          <Label htmlFor="product-photo">产品图</Label>
          <Input
            id="product-photo"
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={(event) => setProductPhoto(event.target.files?.[0] ?? null)}
          />
          <Label htmlFor="points">卖点，一行一条</Label>
          <Textarea id="points" value={points} onChange={(event) => setPoints(event.target.value)} />
        </div>

        <div className="mt-6 grid gap-2">
          <Label htmlFor="role">人物身份</Label>
          <Input id="role" value={role} onChange={(event) => setRole(event.target.value)} />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={consent}
              onChange={(event) => {
                setConsent(event.target.checked);
                if (!event.target.checked) setVoiceId("");
              }}
            />
            已获得肖像授权
          </label>
          <Label htmlFor="voice">声音编号</Label>
          <Input
            id="voice"
            value={voiceId}
            disabled={!consent}
            placeholder={consent ? "可选" : "先勾选肖像授权"}
            onChange={(event) => setVoiceId(event.target.value)}
          />
        </div>

        <div className="mt-6 grid gap-2 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor="phone">电话</Label>
            <Input id="phone" value={phone} onChange={(event) => setPhone(event.target.value)} />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="website">官网</Label>
            <Input id="website" value={website} onChange={(event) => setWebsite(event.target.value)} />
          </div>
        </div>

        {error ? (
          <p role="alert" className="mt-4 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        <Button type="submit" size="lg" className="mt-6 w-full" disabled={busy}>
          {busy ? "正在整理资料" : "保存品牌资料"}
        </Button>
      </form>

      <Card className="min-w-0 p-5">
        <h2 className="text-sm font-medium">当前资料</h2>
        {saved ? (
          <div className="mt-4 grid gap-3 text-sm leading-6">
            <p>已保存。之后新建的项目会自动套用这份 Logo、色彩、字体、行动号召和卖点。</p>
            {saved.previews.logo ? (
              // The preview is a data URL of our own cutout.
              // eslint-disable-next-line @next/next/no-img-element
              <img src={saved.previews.logo} alt="" className="h-16 w-16 rounded-md border border-border bg-white object-contain" />
            ) : null}
            <p>
              主色 {saved.brand_kit.colors.primary}，辅色 {saved.brand_kit.colors.secondary}，强调色{" "}
              {saved.brand_kit.colors.accent}
            </p>
            <p>
              字体 {saved.brand_kit.fonts.title} / {saved.brand_kit.fonts.body}
            </p>
            <p>
              行动号召 {saved.brand_kit.cta.phone || "未填电话"} {saved.brand_kit.cta.website}
            </p>
            {saved.brand_kit.products.map((product) => (
              <p key={product.name}>
                {product.name}：{product.selling_points.join("、") || "还没有卖点"}
              </p>
            ))}
            <p>未勾选肖像授权的人物不会出镜，也不能克隆声音。</p>
          </div>
        ) : (
          <p className="mt-4 text-sm leading-6 text-muted-foreground">保存之后，这里会显示抠好的 Logo 和提取出的颜色。</p>
        )}
      </Card>
    </div>
  );
}
