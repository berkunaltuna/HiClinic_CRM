export const SERVICE_TAGS = [
  "service:TMJ",
  "service:Aesthetics",
  "service:HairTransplant",
  "service:Dentistry",
];

export const PIPELINE_STAGES = [
  "new",
  "contacted",
  "waiting_for_response",
  "interested",
  "appointment_booked",
  "pro_forma_sent",
  "waiting_on_dates",
  "deposit_requested",
  "deposit_paid",
  "treatment_completed",
  "lost",
];

export const LOST_REASONS = [
  "No response",
  "Too expensive",
  "Chose another clinic",
  "Not suitable candidate",
  "Cancelled",
  "Other",
];

const LEAD_SOURCE_META: Record<string, { label: string; color: string }> = {
  facebook: { label: "Facebook", color: "#1877F2" },
  instagram: { label: "Instagram", color: "#E1306C" },
  google: { label: "Google Ads", color: "#EA4335" },
  whatsapp: { label: "WhatsApp", color: "#25D366" },
  referral: { label: "Referral", color: "#8b5cf6" },
  website: { label: "Website", color: "#0ea5e9" },
};

export function sourceMeta(source?: string | null): { label: string; color: string } {
  if (!source || !source.trim()) return { label: "Unknown", color: "#94a3b8" };
  const key = source.trim().toLowerCase();
  return LEAD_SOURCE_META[key] || { label: source, color: "#64748b" };
}

const STAGE_ACCENT: Record<string, string> = {
  new: "#3b82f6",
  contacted: "#3b82f6",
  waiting_for_response: "#3b82f6",
  interested: "#3b82f6",
  appointment_booked: "#6366f1",
  pro_forma_sent: "#6366f1",
  waiting_on_dates: "#6366f1",
  deposit_requested: "#f59e0b",
  deposit_paid: "#10b981",
  treatment_completed: "#10b981",
  lost: "#94a3b8",
};

export function stageAccent(stage: string): string {
  return STAGE_ACCENT[stage] || "#94a3b8";
}

const CALLING_CODE_COUNTRY: [string, string][] = [
  ["971", "AE"],
  ["358", "FI"],
  ["353", "IE"],
  ["351", "PT"],
  ["380", "UA"],
  ["420", "CZ"],
  ["44", "UK"],
  ["49", "DE"],
  ["33", "FR"],
  ["31", "NL"],
  ["46", "SE"],
  ["39", "IT"],
  ["43", "AT"],
  ["34", "ES"],
  ["41", "CH"],
  ["45", "DK"],
  ["47", "NO"],
  ["32", "BE"],
  ["30", "GR"],
  ["90", "TR"],
  ["48", "PL"],
  ["36", "HU"],
  ["1", "US"],
  ["7", "RU"],
].sort((a, b) => b[0].length - a[0].length);

export function countryFromPhone(phone?: string | null): string | null {
  if (!phone) return null;
  const digits = phone.trim().replace(/[^\d+]/g, "");
  let normalized: string | null;
  if (digits.startsWith("+")) normalized = digits.slice(1);
  else if (digits.startsWith("00")) normalized = digits.slice(2);
  else if (digits.startsWith("0")) normalized = null; // national format, no country code present
  else normalized = digits; // assume the calling code is already the leading digits
  if (!normalized) return null;
  for (const [code, country] of CALLING_CODE_COUNTRY) {
    if (normalized.startsWith(code)) return country;
  }
  return null;
}

export function ownerInitials(email?: string | null): string {
  if (!email) return "—";
  const local = email.split("@")[0] || email;
  const parts = local.split(/[._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return local.slice(0, 2).toUpperCase();
}

export function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    new: "New",
    contacted: "Contacted",
    waiting_for_response: "Waiting For Response",
    interested: "Interested",
    appointment_booked: "Appointment Booked",
    pro_forma_sent: "Pro Forma Sent",
    waiting_on_dates: "Waiting on Dates",
    deposit_requested: "Deposit Requested",
    deposit_paid: "Deposit Paid",
    treatment_completed: "Treatment Completed",
    lost: "Lost",
    consult_booked: "Appointment Booked",
    treatment_done: "Treatment Completed",
  };
  return labels[stage] || (stage || "").replaceAll("_", " ").replace(/^./, (m) => m.toUpperCase());
}
