/** Degraded concept cards. HTTP 200 can still mean the cards are a fallback. */

export type ConceptStatus = {
  concept_degraded?: boolean;
  concept_ok?: boolean | null;
  concept_text_source?: string | null;
};

export function conceptIsDegraded(status: ConceptStatus | null | undefined): boolean {
  if (!status) return false;
  if (status.concept_degraded === true) return true;
  if (status.concept_ok === false) return true;
  if (status.concept_text_source === "template_fallback") return true;
  return false;
}

export function conceptNotice(status: ConceptStatus | null | undefined): string | null {
  if (!conceptIsDegraded(status)) return null;
  if (status?.concept_text_source === "template_fallback") {
    return "方案卡是模板兜底，不能当作质检通过。";
  }
  return "方案卡未通过，不能当作质检通过。";
}
