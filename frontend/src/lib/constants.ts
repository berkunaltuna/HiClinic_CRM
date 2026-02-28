export const SERVICE_TAGS = [
  "service:TMJ",
  "service:Aesthetics",
  "service:HairTransplant",
  "service:Dentistry",
];

export const PIPELINE_STAGES = [
  "new",
  "contacted",
  "consult_booked",
  "deposit_paid",
  "treatment_done",
  "lost",
];

export function stageLabel(stage: string): string {
  const s = (stage || "").replaceAll("_", " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}
