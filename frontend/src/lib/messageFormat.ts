// Plain-text message formatting, matching api/app/services/message_format.py:
// blank line = new paragraph, *text* = bold, web links become clickable.

const HTML_TAG_RE = /<\s*\/?\s*(p|br|b|strong|i|em|u|a|div|span|ul|ol|li|h[1-6]|table|tr|td|img)\b[^>]*>/i;
const BOLD_RE = /\*(\S(?:[^*\n]*?\S)?)\*/g;
const URL_RE = /(https?:\/\/[^\s<]+[^\s<.,;:!?)\]'"])/g;
const TOKEN_RE = /\{\{\s*([a-zA-Z0-9_]+)\s*\}\}/g;

export function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function looksLikeHtml(text: string | null | undefined): boolean {
  return HTML_TAG_RE.test(text || "");
}

export function textToHtml(text: string): string {
  const paragraphs = (text || "").replace(/\r\n/g, "\n").trim().split(/\n\s*\n/).filter((p) => p.trim());
  const body = paragraphs
    .map((p) => {
      let safe = escapeHtml(p.trim());
      safe = safe.replace(URL_RE, '<a href="$1">$1</a>');
      safe = safe.replace(BOLD_RE, "<b>$1</b>");
      return `<p>${safe.replace(/\n/g, "<br>")}</p>`;
    })
    .join("");
  return `<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.5;color:#1f2937">${body}</div>`;
}

/** WhatsApp shows *bold* natively; this is only for the on-screen preview. */
export function whatsappToHtml(text: string): string {
  return escapeHtml(text || "").replace(BOLD_RE, "<b>$1</b>").replace(/\n/g, "<br>");
}

/** One-click conversion of an old HTML template into the plain-text format. */
export function htmlToText(html: string): string {
  let s = html || "";
  s = s.replace(/<a\b[^>]*href="([^"]*)"[^>]*>(.*?)<\/a>/gi, (_m, href, label) => (label === href ? href : `${label} (${href})`));
  s = s.replace(/<\s*(b|strong)\b[^>]*>(.*?)<\s*\/\s*\1\s*>/gi, "*$2*");
  s = s.replace(/<\s*br\s*\/?>/gi, "\n");
  s = s.replace(/<\s*\/\s*(p|div|h[1-6]|li|tr)\s*>/gi, "\n\n");
  s = s.replace(/<[^>]+>/g, "");
  s = s.replace(/&nbsp;/g, " ").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");
  return s.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

export function fillFields(text: string, values: Record<string, string>): string {
  return (text || "").replace(TOKEN_RE, (_m, key) => values[key] ?? `{{${key}}}`);
}
