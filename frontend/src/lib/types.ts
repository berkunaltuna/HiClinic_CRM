export type UUID = string;

export type AuthTokenOut = {
  access_token: string;
  token_type?: string;
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
  amount: string; // numeric comes as string
  status: string;
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
  channel: string;
  status: string;
  template_id: UUID | null;
  body: string | null;
  variables: Record<string, any> | null;
  not_before_at: string | null;
  cancel_on_inbound: boolean;
  created_at: string;
  sent_at: string | null;
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
