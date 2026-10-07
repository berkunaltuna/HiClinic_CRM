"use client";

import { FormEvent, useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import type { AppointmentOut, EventDayOut, EventOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

type DayDraft = {
  start_time: string;
  end_time: string;
  slot_minutes: number;
  break_start_time: string;
  break_end_time: string;
  label: string;
};

const hhmm = (t: string | null) => (t ? t.slice(0, 5) : "");

function toDraft(d: EventDayOut): DayDraft {
  return {
    start_time: hhmm(d.start_time),
    end_time: hhmm(d.end_time),
    slot_minutes: d.slot_minutes,
    break_start_time: hhmm(d.break_start_time),
    break_end_time: hhmm(d.break_end_time),
    label: d.label || "",
  };
}

function weekday(day: string) {
  return new Date(`${day}T00:00:00`).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" });
}

export function GearIcon({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function EventSettingsPanel({ event, appointments, onSaved }: { event: EventOut; appointments: AppointmentOut[]; onSaved: () => Promise<void> }) {
  const toast = useToast();
  const [name, setName] = useState(event.name);
  const [location, setLocation] = useState(event.location || "");
  const [capacity, setCapacity] = useState(event.slot_capacity || 1);
  const [savingEvent, setSavingEvent] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, DayDraft>>({});
  const [savingDay, setSavingDay] = useState<string | null>(null);

  useEffect(() => {
    setName(event.name);
    setLocation(event.location || "");
    setCapacity(event.slot_capacity || 1);
    setDrafts(Object.fromEntries(event.days.map((d) => [d.id, toDraft(d)])));
  }, [event]);

  async function saveEvent(e: FormEvent) {
    e.preventDefault();
    setSavingEvent(true);
    try {
      await apiFetch<EventOut>(`/events/${event.id}`, {
        method: "PATCH",
        body: JSON.stringify({ name, location: location || null, slot_capacity: capacity }),
      });
      toast.push("Event updated");
      await onSaved();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update event", "error");
    } finally {
      setSavingEvent(false);
    }
  }

  function updateDraft(dayId: string, patch: Partial<DayDraft>) {
    setDrafts((cur) => ({ ...cur, [dayId]: { ...cur[dayId], ...patch } }));
  }

  async function saveDay(d: EventDayOut) {
    const draft = drafts[d.id];
    if (!draft) return;
    if (!!draft.break_start_time !== !!draft.break_end_time) {
      toast.push("Set both break start and break end, or clear both", "error");
      return;
    }
    setSavingDay(d.id);
    try {
      await apiFetch<EventDayOut>(`/events/${event.id}/days/${d.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          start_time: draft.start_time,
          end_time: draft.end_time,
          slot_minutes: draft.slot_minutes,
          break_start_time: draft.break_start_time || null,
          break_end_time: draft.break_end_time || null,
          label: draft.label || null,
        }),
      });
      toast.push(`${d.label || weekday(d.day)} hours updated`);
      await onSaved();
    } catch (err: any) {
      toast.push(err?.message || "Failed to update day hours", "error");
    } finally {
      setSavingDay(null);
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>General</div>
        <form className="cardBody grid" onSubmit={saveEvent}>
          <div className="grid" style={{ gridTemplateColumns: "2fr 2fr 1fr", alignItems: "end" }}>
            <label>Event name<input className="formField" value={name} onChange={(e) => setName(e.target.value)} required /></label>
            <label>Location / address<input className="formField" value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Location / address" /></label>
            <label>Capacity per slot<input className="formField" type="number" min={1} max={50} value={capacity} onChange={(e) => setCapacity(Number(e.target.value))} /></label>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
            <div className="muted">If you reduce capacity, the CRM checks existing slots first and blocks unsafe changes.</div>
            <button className="btn btnPrimary" type="submit" disabled={savingEvent}>{savingEvent ? "Saving…" : "Save event settings"}</button>
          </div>
        </form>
      </section>

      <section className="card">
        <div className="cardHeader" style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
          <b>Day hours</b>
          <span className="muted">Each day is saved on its own. Changes that would leave a booking outside the hours are blocked.</span>
        </div>
        <div className="cardBody" style={{ overflowX: "auto" }}>
          <table className="table">
            <thead>
              <tr>
                <th>Day</th>
                <th>Label</th>
                <th>Opens</th>
                <th>Closes</th>
                <th>Slot (min)</th>
                <th>Break from</th>
                <th>Break to</th>
                <th>Bookings</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {event.days.map((d) => {
                const draft = drafts[d.id];
                if (!draft) return null;
                const original = toDraft(d);
                const dirty = JSON.stringify(original) !== JSON.stringify(draft);
                const booked = appointments.filter((a) => a.status !== "cancelled" && a.starts_at.slice(0, 10) === d.day).length;
                return (
                  <tr key={d.id} style={{ background: dirty ? "rgba(30,103,150,0.06)" : undefined }}>
                    <td style={{ fontWeight: 700, whiteSpace: "nowrap" }}>{weekday(d.day)}</td>
                    <td><input className="formField" value={draft.label} onChange={(e) => updateDraft(d.id, { label: e.target.value })} placeholder="Optional" style={{ minWidth: 110 }} /></td>
                    <td><input className="formField" type="time" step={300} value={draft.start_time} onChange={(e) => updateDraft(d.id, { start_time: e.target.value })} required /></td>
                    <td><input className="formField" type="time" step={300} value={draft.end_time} onChange={(e) => updateDraft(d.id, { end_time: e.target.value })} required /></td>
                    <td><input className="formField" type="number" min={5} max={240} step={5} value={draft.slot_minutes} onChange={(e) => updateDraft(d.id, { slot_minutes: Number(e.target.value) })} style={{ width: 80 }} /></td>
                    <td><input className="formField" type="time" step={300} value={draft.break_start_time} onChange={(e) => updateDraft(d.id, { break_start_time: e.target.value })} /></td>
                    <td><input className="formField" type="time" step={300} value={draft.break_end_time} onChange={(e) => updateDraft(d.id, { break_end_time: e.target.value })} /></td>
                    <td className="muted">{booked}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="btn btnPrimary" type="button" disabled={!dirty || savingDay === d.id} onClick={() => void saveDay(d)}>
                        {savingDay === d.id ? "Saving…" : "Save"}
                      </button>
                      {dirty && <button className="btn" type="button" style={{ marginLeft: 6 }} onClick={() => updateDraft(d.id, original)}>Reset</button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
