import type { CustomerOut, InboxCustomerOut, TemplateOut } from "@/lib/types";

export type WhatsAppCustomer = Pick<CustomerOut | InboxCustomerOut, "name" | "phone"> & Partial<CustomerOut & InboxCustomerOut>;

export function normalisePhoneForWhatsApp(phone?: string | null): string | null {
  if (!phone) return null;

  const trimmed = phone.trim();
  if (!trimmed) return null;

  let digits = trimmed.replace(/[^0-9]/g, "");
  if (!digits) return null;

  // 00XXXXXXXX -> XXXXXXXXX
  if (digits.startsWith("00")) {
    digits = digits.slice(2);
  }

  // Already international (44...)
  if (digits.startsWith("44")) {
    return digits;
  }

  // Local UK number
  if (digits.startsWith("0")) {
    return "44" + digits.slice(1);
  }

  return digits;
}

export function renderTemplate(template: string, customer: WhatsAppCustomer): string {
  const latestDeal = customer.latest_deal || null;
  const values: Record<string, string> = {
    customer_name: customer.name || "",
    name: customer.name || "",
    phone: customer.phone || "",
    treatment_interest: latestDeal?.treatment_interest || "",
    preferred_day: latestDeal?.preferred_consultation_day || "",
    preferred_consultation_day: latestDeal?.preferred_consultation_day || "",
    seminar_interest: latestDeal?.seminar_preference || "",
    seminar_preference: latestDeal?.seminar_preference || "",
  };
  return template.replace(/{{\s*([a-zA-Z0-9_]+)\s*}}/g, (_match, key) => values[key] ?? "");
}

export function buildWhatsAppLink(customer: WhatsAppCustomer, message?: string): string | null {
  const phone = normalisePhoneForWhatsApp(customer.phone);
  if (!phone) return null;
  const text = (message || "").trim();
  return `https://wa.me/${phone}${text ? `?text=${encodeURIComponent(text)}` : ""}`;
}

export function defaultWhatsAppMessage(customer: WhatsAppCustomer): string {
  return renderTemplate(
    "Hi {{customer_name}}, thank you for your interest in Health Clinic Turkiye. How can I help you today?",
    customer,
  );
}

export function whatsappTemplates(templates: TemplateOut[]): TemplateOut[] {
  return templates.filter((t) => (t.channel || "").toLowerCase() === "whatsapp");
}
