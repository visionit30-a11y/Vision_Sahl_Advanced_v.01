/**
 * نقاط الكسر المعتمدة — المصدر الوحيد لأي منطق استجابة في TypeScript.
 * أي قيمة هنا يجب أن تطابق tokens/breakpoints.css حرفيًا.
 */
export const BREAKPOINTS = {
  tablet: 640,
  laptop: 1024,
  desktop: 1440,
} as const;

export type BreakpointName = keyof typeof BREAKPOINTS;
