/** 自绘的几何占位，不是客户照片，也不是第三方素材。画面里不写字。 */

function svg(body: string): string {
  const markup = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 180">${body}</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
}

const ground = `<rect width="320" height="180" fill="#141417"/>`;

export function productFrame(): string {
  return svg(
    `${ground}<rect x="118" y="28" width="84" height="124" rx="16" fill="#2E5BFF"/><rect x="136" y="46" width="48" height="72" rx="6" fill="#f5f5f7"/><circle cx="160" cy="132" r="8" fill="#0c0c0e"/>`,
  );
}

export function shotFrame(variant: 1 | 2 | 3): string {
  if (variant === 1) {
    return svg(
      `${ground}<rect x="0" y="96" width="320" height="84" fill="#1c1c21"/><rect x="36" y="40" width="120" height="78" rx="8" fill="#2E5BFF"/><circle cx="230" cy="58" r="22" fill="#f5f5f7"/>`,
    );
  }
  if (variant === 2) {
    return svg(
      `${ground}<rect x="28" y="36" width="168" height="108" rx="12" fill="#1c1c21"/><rect x="188" y="64" width="104" height="80" rx="8" fill="#2E5BFF"/><circle cx="78" cy="86" r="18" fill="#f5f5f7"/>`,
    );
  }
  return svg(
    `${ground}<rect x="24" y="32" width="128" height="116" rx="10" fill="#2E5BFF"/><rect x="168" y="32" width="128" height="52" rx="8" fill="#f5f5f7"/><rect x="168" y="96" width="128" height="52" rx="8" fill="#1c1c21"/>`,
  );
}

export function finalFrame(): string {
  return svg(
    `${ground}<rect x="20" y="28" width="132" height="124" rx="10" fill="#1c1c21"/><rect x="168" y="28" width="132" height="56" rx="8" fill="#2E5BFF"/><rect x="168" y="96" width="132" height="56" rx="8" fill="#f5f5f7"/>`,
  );
}
