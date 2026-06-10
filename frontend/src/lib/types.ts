export type UUID = string;

export type AuthTokenOut = {
  access_token: string;
  token_type?: string;
};

export type DealLeadFields = {
  treatment_interest: string | null;
  preferred_consultation_day: string | null;
  seminar_preference: string | null;
};

export type CustomerOut = {
  id: UUID;
  name: string;
  email: string | null;
  phone: string | null;
  company: string | null;
  next_follow_up_at: string | null;
  can_contact: boolean;
  language: string | null;
  stage: string;
  tag_names: string[];
  latest_deal: DealOut | null;
  lead_source: string | null;
  form_id: string | null;
  form_name: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  adset_id: string | null;
  adset_name: string | null;
  ad_id: string | null;
  ad_name: string | null;
};

export type InboxCustomerOut = {
  id: UUID;
  name: string;
  email: string | null;
  phone: string | null;
  company: string | null;
  stage: string;
  tags: string[];
  next_follow_up_at: string | null;
  last_inbound_at: string | null;
  last_outbound_at: string | null;
  last_activity_at: string | null;
  last_activity_direction: string | null;
  bucket: "followup_due" | "open" | "waiting" | "closed" | string;
  latest_deal: DealOut | null;
  lead_source: string | null;
  form_id: string | null;
  form_name: string | null;
  campaign_id: string | null;
  campaign_name: string | null;
  adset_id: string | null;
  adset_name: string | null;
  ad_id: string | null;
  ad_name: string | null;
};

export type ThreadItem = {
  kind: "interaction" | "outbound_message" | string;
  id: UUID;
  direction: "inbound" | "outbound" | string;
  channel: string;
  occurred_at: string;
  content: string | null;
  subject: string | null;
  status: string | null;
  template_id: UUID | null;
};

export type DealOut = {
  id: UUID;
  customer_id: UUID;
  amount: string;
  status: string;
  treatment_interest: string | null;
  preferred_consultation_day: string | null;
  seminar_preference: string | null;
  event_id: UUID | null;
  confirmation_sent_at: string | null;
  confirmation_channel: string | null;
  confirmation_template_id: UUID | null;
  confirmed_by_user_id: UUID | null;
  lost_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type FollowupItem = {
  customer_id: UUID;
  customer_name: string;
  customer_phone: string | null;
  customer_email: string | null;
  customer_company: string | null;
  stage: string;
  next_follow_up_at: string;
};

export type TagOut = {
  id: UUID;
  name: string;
};

export type TemplateOut = {
  id: UUID;
  channel: "email" | "whatsapp" | string;
  name: string;
  subject: string | null;
  body: string;
  category: string;
  language: string;
  created_at: string;
  updated_at: string;
};

export type OutboundMessageOut = {
  id: UUID;
  customer_id: UUID;
  customer_name?: string | null;
  channel: string;
  status: string;
  template_id: UUID | null;
  template_name?: string | null;
  body: string | null;
  variables: Record<string, any> | null;
  not_before_at: string | null;
  cancel_on_inbound: boolean;
  created_at: string;
  updated_at?: string | null;
  sent_at?: string | null;
};

export type KPIResponse = {
  start: string;
  end: string;
  leads_created: number;
  outbound_sent: number;
  inbound_received: number;
  median_first_response_seconds: number | null;
  outcomes: Record<string, number>;
  conversion_rates: Record<string, number>;
};

export type UserOut = {
  id: UUID;
  email: string;
  role: string;
  created_at: string;
  updated_at: string;
};

export type AuditLogOut = {
  id: UUID;
  actor_user_id: UUID | null;
  actor_email: string | null;
  action: string;
  entity_type: string;
  entity_id: UUID | null;
  before: Record<string, any> | null;
  after: Record<string, any> | null;
  meta: Record<string, any> | null;
  created_at: string;
};

export type EventDayOut = {
  id: UUID;
  event_id: UUID;
  day: string;
  start_time: string;
  end_time: string;
  slot_minutes: number;
  break_start_time: string | null;
  break_end_time: string | null;
  label: string | null;
};

export type EventOut = {
  id: UUID;
  owner_user_id: UUID;
  name: string;
  location: string | null;
  description: string | null;
  starts_on: string;
  ends_on: string;
  default_slot_minutes: number;
  slot_capacity: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  days: EventDayOut[];
};

export type AppointmentOut = {
  id: UUID;
  event_id: UUID;
  customer_id: UUID;
  deal_id: UUID | null;
  assigned_user_id: UUID | null;
  starts_at: string;
  ends_at: string;
  appointment_type: string;
  status: string;
  notes: string | null;
  customer_name: string | null;
  customer_phone: string | null;
  deal_treatment_interest: string | null;
  created_at: string;
  updated_at: string;
};

export type AttributionRow = { name: string; count: number };
export type LostReasonRow = { reason: string; count: number };
