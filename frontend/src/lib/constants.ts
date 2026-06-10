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

export function stageLabel(stage: string): string {
  const labels: Record<string, string> = {
    new: "New",
    contacted: "Contacted",
    waiting_for_response: "Waiting For Response",
    interested: "Interested",
    appointment_booked: "Appointment Booked",
    deposit_requested: "Deposit Requested",
    deposit_paid: "Deposit Paid",
    treatment_completed: "Treatment Completed",
    lost: "Lost",
    consult_booked: "Appointment Booked",
    treatment_done: "Treatment Completed",
  };
  return labels[stage] || (stage || "").replaceAll("_", " ").replace(/^./, (m) => m.toUpperCase());
}
