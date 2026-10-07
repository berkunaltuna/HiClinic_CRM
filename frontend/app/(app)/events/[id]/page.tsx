"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { AppointmentOut, CustomerOut, EventOut } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { WhatsAppQuickAction } from "@/components/WhatsAppQuickAction";
import { EventImportWizard } from "@/components/EventImportWizard";
import { EventExportDialog } from "@/components/EventExportDialog";
import { EventSettingsPanel, GearIcon } from "@/components/EventSettingsPanel";

function combine(day: string, time: string) {
  return `${day}T${time}:00`;
}

function addMinutes(_day: string, time: string, mins: number) {
  const [hh, mm] = time.slice(0, 5).split(":").map(Number);
  const total = hh * 60 + mm + mins;
  const nextH = Math.floor(total / 60);
  const nextM = total % 60;
  return `${String(nextH).padStart(2, "0")}:${String(nextM).padStart(2, "0")}`;
}

function slots(day: string, start: string, end: string, step: number) {
  const out: string[] = [];
  let t = start.slice(0, 5);
  while (t < end.slice(0, 5)) {
    out.push(t);
    t = addMinutes(day, t, step);
  }
  return out;
}

export default function EventDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const [event, setEvent] = useState<EventOut | null>(null);
  const [appointments, setAppointments] = useState<AppointmentOut[]>([]);
  const [customers, setCustomers] = useState<CustomerOut[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [customerQuery, setCustomerQuery] = useState("");
  const [customerListOpen, setCustomerListOpen] = useState(false);
  const [day, setDay] = useState("");
  const [time, setTime] = useState("09:00");
  const [notes, setNotes] = useState("");
  const [view, setView] = useState<"timetable" | "settings">("timetable");
  const [showImport, setShowImport] = useState(false);
  const [showExport, setShowExport] = useState(false);

  async function load() {
    const ev = await apiFetch<EventOut>(`/events/${id}`);
    setEvent(ev);
    setDay((current) => current || ev.days[0]?.day || ev.starts_on);
    setAppointments(await apiFetch<AppointmentOut[]>(`/events/${id}/appointments`));
    setCustomers(await apiFetch<CustomerOut[]>("/customers"));
  }

  useEffect(() => { void load().catch((err) => toast.push(err?.message || "Failed to load timetable", "error")); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedDay = useMemo(() => event?.days.find((d) => d.day === day) || event?.days[0], [event, day]);
  const selectedCustomer = customers.find((c) => c.id === customerId);
  const selectableSlots = useMemo(() => selectedDay ? slots(selectedDay.day, selectedDay.start_time, selectedDay.end_time, selectedDay.slot_minutes) : [], [selectedDay]);

  // Customer search includes every customer regardless of stage (new, contacted, lost, etc).
  const matchingCustomers = useMemo(() => {
    const query = customerQuery.trim().toLowerCase();
    if (!query) return customers;
    return customers.filter((c) => {
      const haystack = [c.name, c.email, c.phone, c.company].filter(Boolean).join(" ").toLowerCase();
      return haystack.includes(query);
    });
  }, [customers, customerQuery]);

  function selectCustomer(c: CustomerOut) {
    setCustomerId(c.id);
    setCustomerQuery(c.name);
    setCustomerListOpen(false);
  }

  function clearCustomerSelection() {
    setCustomerId("");
    setCustomerQuery("");
  }

  useEffect(() => {
    if (selectableSlots.length && !selectableSlots.includes(time)) setTime(selectableSlots[0]);
  }, [selectableSlots, time]);

  async function book(e: FormEvent) {
    e.preventDefault();
    if (!event || !selectedDay || !customerId) return;
    try {
      const start = combine(selectedDay.day, time);
      const endTime = addMinutes(selectedDay.day, time, selectedDay.slot_minutes);
      const end = combine(selectedDay.day, endTime);
      const customer = customers.find((c) => c.id === customerId);
      await apiFetch<AppointmentOut>(`/events/${event.id}/appointments`, {
        method: "POST",
        body: JSON.stringify({
          customer_id: customerId,
          deal_id: customer?.latest_deal?.id || null,
          starts_at: start,
          ends_at: end,
          appointment_type: "consultation",
          status: "booked",
          notes: notes || null,
        }),
      });
      toast.push("Appointment booked");
      setNotes("");
      clearCustomerSelection();
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to book appointment", "error");
    }
  }

  async function deleteEvent() {
    if (!event || !confirm(`Delete "${event.name}"? This removes its timetable and all booked appointments.`)) return;
    try {
      await apiFetch<void>(`/events/${event.id}`, { method: "DELETE" });
      toast.push("Event deleted");
      router.push("/events");
    } catch (err: any) {
      toast.push(err?.message || "Failed to delete event", "error");
    }
  }

  async function remove(appt: AppointmentOut) {
    if (!event || !confirm(`Remove appointment for ${appt.customer_name}?`)) return;
    await apiFetch<void>(`/events/${event.id}/appointments/${appt.id}`, { method: "DELETE" });
    toast.push("Appointment removed");
    await load();
  }

  if (!event) return <div className="stack"><Topbar title="Event timetable" /><div className="card"><div className="cardBody">Loading…</div></div></div>;

  return (
    <div className="stack">
      <Topbar
        title={event.name}
        right={
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className={view === "settings" ? "btn btnPrimary" : "btn"}
              onClick={() => setView((v) => (v === "settings" ? "timetable" : "settings"))}
              title={view === "settings" ? "Back to timetable" : "Event settings"}
              aria-label="Event settings"
              aria-pressed={view === "settings"}
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <GearIcon />
              {view === "settings" && <span>Back to timetable</span>}
            </button>
            <button className="btn" onClick={() => setShowExport(true)}>Export</button>
            <button className="btn" onClick={() => setShowImport(true)}>Import bookings</button>
            <button className="btn btnDanger" onClick={() => void deleteEvent()}>Delete event</button>
          </div>
        }
      />
      {showImport && (
        <EventImportWizard
          eventId={event.id}
          onClose={() => setShowImport(false)}
          onImported={() => { void load(); }}
        />
      )}
      {showExport && <EventExportDialog event={event} onClose={() => setShowExport(false)} />}
      {view === "settings" ? (
        <EventSettingsPanel event={event} appointments={appointments} onSaved={load} />
      ) : (
        <div className="grid" style={{ gridTemplateColumns: "320px 1fr", alignItems: "start" }}>
          <section className="card">
            <div className="cardHeader" style={{ fontWeight: 900 }}>Book customer</div>
            <form className="cardBody grid" onSubmit={book}>
              <div style={{ position: "relative" }}>
                <input
                  className="formField"
                  value={customerQuery}
                  onChange={(e) => {
                    setCustomerQuery(e.target.value);
                    setCustomerId("");
                    setCustomerListOpen(true);
                  }}
                  onFocus={() => setCustomerListOpen(true)}
                  onBlur={() => setTimeout(() => setCustomerListOpen(false), 150)}
                  placeholder="Search customers by name, email or phone…"
                  required={!customerId}
                />
                {customerId && (
                  <button
                    type="button"
                    className="btn"
                    onClick={clearCustomerSelection}
                    style={{ position: "absolute", right: 4, top: 4, bottom: 4, padding: "0 10px" }}
                  >
                    Clear
                  </button>
                )}
                {customerListOpen && !customerId && (
                  <div
                    className="card"
                    style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, maxHeight: 260, overflowY: "auto", marginTop: 4 }}
                  >
                    {matchingCustomers.length === 0 ? (
                      <div className="cardBody muted">No customers found</div>
                    ) : (
                      matchingCustomers.map((c) => (
                        <div
                          key={c.id}
                          className="cardBody"
                          style={{ cursor: "pointer", padding: "8px 12px", borderTop: "1px solid var(--border)" }}
                          onMouseDown={() => selectCustomer(c)}
                        >
                          <div style={{ fontWeight: 700 }}>{c.name}</div>
                          <div className="muted" style={{ fontSize: 12 }}>
                            {[c.email, c.phone].filter(Boolean).join(" · ") || "No contact info"}
                            {c.latest_deal?.treatment_interest ? ` · ${c.latest_deal.treatment_interest}` : ""}
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                )}
              </div>
              <select className="formField" value={day} onChange={(e) => setDay(e.target.value)}>
                {event.days.map((d) => <option key={d.id} value={d.day}>{d.label || d.day}</option>)}
              </select>
              <select className="formField" value={time} onChange={(e) => setTime(e.target.value)}>
                {selectableSlots.map((slot) => <option key={slot} value={slot}>{slot}</option>)}
              </select>
              <textarea className="formField" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" />
              {selectedCustomer && <WhatsAppQuickAction customer={selectedCustomer} />}
              <button className="btn btnPrimary" type="submit">Place in timetable</button>
            </form>
          </section>

          <section className="card">
            <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between" }}>
              <b>Timetable</b>
              <span className="muted">{event.location || "No location"} · capacity {event.slot_capacity || 1}/slot</span>
            </div>
            <div className="cardBody grid">
              {event.days.map((d) => {
                const appts = appointments.filter((a) => a.starts_at.slice(0, 10) === d.day);
                const capacity = event.slot_capacity || 1;
                return (
                  <div key={d.id} className="card" style={{ boxShadow: "none" }}>
                    <div className="cardHeader"><b>{d.label || d.day}</b> <span className="muted">{d.start_time.slice(0,5)}–{d.end_time.slice(0,5)} / {d.slot_minutes} min</span></div>
                    <div className="cardBody">
                      <table className="table">
                        <tbody>
                          {slots(d.day, d.start_time, d.end_time, d.slot_minutes).map((t) => {
                            const booked = appts.filter((a) => a.starts_at.slice(11, 16) === t);
                            const full = booked.length >= capacity;
                            return (
                              <tr key={`${d.day}-${t}`} style={{ background: booked.length ? "rgba(30,103,150,0.06)" : undefined }}>
                                <td style={{ width: 90, fontWeight: 700 }}>{t}</td>
                                <td>
                                  <div className="muted" style={{ fontSize: 12, marginBottom: booked.length ? 6 : 0 }}>{booked.length}/{capacity} {full ? "Full" : "Booked"}</div>
                                  {booked.length ? booked.map((appt) => (
                                    <div key={appt.id} style={{ padding: "6px 0", borderTop: "1px solid var(--border)" }}>
                                      <b>{appt.customer_name}</b>
                                      <div className="muted">{appt.deal_treatment_interest || appt.appointment_type} · {appt.status}</div>
                                      {appt.notes && <div>{appt.notes}</div>}
                                    </div>
                                  )) : <span className="muted">Available</span>}
                                </td>
                                <td style={{ width: 120 }}>
                                  {booked.map((appt) => <button key={appt.id} className="btn" onClick={() => void remove(appt)} style={{ marginBottom: 4 }}>Remove</button>)}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
