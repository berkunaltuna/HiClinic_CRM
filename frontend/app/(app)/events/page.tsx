"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Topbar } from "@/components/Topbar";
import { apiFetch } from "@/lib/api";
import type { EventOut } from "@/lib/types";
import { useToast } from "@/components/Toast";

export default function EventsPage() {
  const toast = useToast();
  const [events, setEvents] = useState<EventOut[]>([]);
  const [busy, setBusy] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("London OPD Event");
  const [location, setLocation] = useState("London");
  const [startsOn, setStartsOn] = useState("2026-06-27");
  const [endsOn, setEndsOn] = useState("2026-06-28");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("17:00");
  const [slotMinutes, setSlotMinutes] = useState(30);
  const [slotCapacity, setSlotCapacity] = useState(1);

  async function load() {
    setBusy(true);
    try {
      setEvents(await apiFetch<EventOut[]>("/events"));
    } catch (err: any) {
      toast.push(err?.message || "Failed to load events", "error");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { void load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function datesBetween(start: string, end: string) {
    const out: string[] = [];
    const s = new Date(`${start}T00:00:00`);
    const e = new Date(`${end}T00:00:00`);
    for (let d = s; d <= e; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
      out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
    }
    return out;
  }

  async function createEvent(e: FormEvent) {
    e.preventDefault();
    try {
      const days = datesBetween(startsOn, endsOn).map((day) => ({
        day,
        start_time: startTime,
        end_time: endTime,
        slot_minutes: slotMinutes,
      }));
      await apiFetch<EventOut>("/events", {
        method: "POST",
        body: JSON.stringify({
          name,
          location: location || null,
          starts_on: startsOn,
          ends_on: endsOn,
          default_slot_minutes: slotMinutes,
          slot_capacity: slotCapacity,
          days,
        }),
      });
      toast.push("Event created");
      setShowNew(false);
      await load();
    } catch (err: any) {
      toast.push(err?.message || "Failed to create event", "error");
    }
  }

  return (
    <div className="stack">
      <Topbar title="Events" right={<button className="btn btnPrimary" onClick={() => setShowNew(true)}>New event</button>} />

      {showNew && (
        <section className="card">
          <div className="cardHeader" style={{ fontWeight: 900 }}>Create configurable event</div>
          <form className="cardBody grid" onSubmit={createEvent}>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Event name" required />
            <input value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Location / address" />
            <div className="grid" style={{ gridTemplateColumns: "repeat(6, 1fr)" }}>
              <label>Start date<input type="date" value={startsOn} onChange={(e) => setStartsOn(e.target.value)} /></label>
              <label>End date<input type="date" value={endsOn} onChange={(e) => setEndsOn(e.target.value)} /></label>
              <label>Day starts<input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} /></label>
              <label>Day ends<input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} /></label>
              <label>Slot minutes<input type="number" min={5} max={240} value={slotMinutes} onChange={(e) => setSlotMinutes(Number(e.target.value))} /></label>
              <label>Capacity/slot<input type="number" min={1} max={50} value={slotCapacity} onChange={(e) => setSlotCapacity(Number(e.target.value))} /></label>
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button className="btn btnPrimary" type="submit">Create</button>
              <button className="btn" type="button" onClick={() => setShowNew(false)}>Cancel</button>
            </div>
          </form>
        </section>
      )}

      <section className="card">
        <div className="cardHeader" style={{ fontWeight: 900 }}>Event list</div>
        <div className="cardBody">
          {busy ? "Loading…" : (
            <table className="table">
              <thead><tr><th>Event</th><th>Dates</th><th>Location</th><th>Slot</th><th>Capacity</th><th></th></tr></thead>
              <tbody>
                {events.map((ev) => (
                  <tr key={ev.id}>
                    <td><b>{ev.name}</b></td>
                    <td>{ev.starts_on} → {ev.ends_on}</td>
                    <td>{ev.location || "—"}</td>
                    <td>{ev.default_slot_minutes} min</td>
                    <td>{ev.slot_capacity || 1}/slot</td>
                    <td><Link className="btn" href={`/events/${ev.id}`}>Open timetable</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </section>
    </div>
  );
}
