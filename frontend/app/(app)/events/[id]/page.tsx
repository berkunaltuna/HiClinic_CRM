"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { AppointmentOut, CustomerOut, EventOut } from "@/lib/types";
import { useToast } from "@/components/Toast";
import { WhatsAppQuickAction } from "@/components/WhatsAppQuickAction";

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
  const toast = useToast();
  const [event, setEvent] = useState<EventOut | null>(null);
  const [appointments, setAppointments] = useState<AppointmentOut[]>([]);
  const [customers, setCustomers] = useState<CustomerOut[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [day, setDay] = useState("");
  const [time, setTime] = useState("09:00");
  const [notes, setNotes] = useState("");
  const [editName, setEditName] = useState("");
  const [editLocation, setEditLocation] = useState("");
  const [editCapacity, setEditCapacity] = useState(1);
  const [savingEvent, setSavingEvent] = useState(false);

  async function load() {
    const ev = await apiFetch<EventOut>(`/events/${id}`);
    setEvent(ev);
    setDay((current) => current || ev.days[0]?.day || ev.starts_on);
    setEditName(ev.name);
    setEditLocation(ev.location || "");
    setEditCapacity(ev.slot_capacity || 1);
    setAppointments(await apiFetch<AppointmentOut[]>(`/events/${id}/appointments`));
    setCustomers(await apiFetch<CustomerOut[]>("/customers"));
  }

  useEffect(() => { void load().catch((err) => toast.push(err?.message || "Failed to load timetable", "error")); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedDay = useMemo(() => event?.days.find((d) => d.day === day) || event?.days[0], [event, day]);
  const selectedCustomer = customers.find((c) => c.id === customerId);
  const selectableSlots = useMemo(() => selectedDay ? slots(selectedDay.day, selectedDay.start_time, selectedDay.end_time, selectedDay.slot_minutes) : [], [selectedDay]);

  useEffect(() => {
    if (selectableSlots.length && !selectableSlots.includes(time)) setTime(selectableSlots[0]);
  }, [selectableSlots, time]);

  async function saveEvent(e: FormEvent) {
    e.preventDefault();
    if (!event) return;
    setSavingEvent(true);
    try {
      const updated = await apiFetch<EventOut>(`/events/${event.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: editName,
          location: editLocation || null,
          slot_capacity: editCapacity,
        }),
      });
      setEvent(updated);
      toast.push("Event updated");
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update event", "error");
    } finally {
      setSavingEvent(false);
    }
  }

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
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to book appointment", "error");
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
      <Topbar title={event.name} />
      <section className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>Event settings</div>
        <form className="cardBody grid" onSubmit={saveEvent}>
          <div className="grid" style={{ gridTemplateColumns: "2fr 2fr 1fr", alignItems: "end" }}>
            <label>Event name<input value={editName} onChange={(e) => setEditName(e.target.value)} required /></label>
            <label>Location / address<input value={editLocation} onChange={(e) => setEditLocation(e.target.value)} placeholder="Location / address" /></label>
            <label>Capacity per slot<input type="number" min={1} max={50} value={editCapacity} onChange={(e) => setEditCapacity(Number(e.target.value))} /></label>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
            <div className="muted">If you reduce capacity, the CRM checks existing slots first and blocks unsafe changes.</div>
            <button className="btn btnPrimary" type="submit" disabled={savingEvent}>{savingEvent ? "Saving…" : "Save event settings"}</button>
          </div>
        </form>
      </section>

      <div className="grid" style={{ gridTemplateColumns: "320px 1fr", alignItems: "start" }}>
        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>Book customer</div>
          <form className="cardBody grid" onSubmit={book}>
            <select value={customerId} onChange={(e) => setCustomerId(e.target.value)} required>
              <option value="">Select CRM customer…</option>
              {customers.map((c) => <option key={c.id} value={c.id}>{c.name} {c.latest_deal?.treatment_interest ? `— ${c.latest_deal.treatment_interest}` : ""}</option>)}
            </select>
            <select value={day} onChange={(e) => setDay(e.target.value)}>
              {event.days.map((d) => <option key={d.id} value={d.day}>{d.label || d.day}</option>)}
            </select>
            <select value={time} onChange={(e) => setTime(e.target.value)}>
              {selectableSlots.map((slot) => <option key={slot} value={slot}>{slot}</option>)}
            </select>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" />
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
    </div>
  );
}
