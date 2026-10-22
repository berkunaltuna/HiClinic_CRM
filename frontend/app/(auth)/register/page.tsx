import Link from "next/link";

// Public self-registration is closed: every account is CRM staff. Admins create
// accounts on the Users page; the first admin is created on the server
// (`python -m app.cli create-first-admin`).
export default function RegisterPage() {
  return (
    <main className="card" style={{ width: "min(520px, 100vw)", padding: 18 }}>
      <h1 style={{ fontSize: 18, fontWeight: 900, margin: 0 }}>Accounts are created by an administrator</h1>
      <p className="muted" style={{ fontSize: 13 }}>
        HiClinic CRM does not offer public sign-up. Ask your administrator to create an account for you.
      </p>
      <div className="muted" style={{ fontSize: 13 }}>
        Already have an account? <Link href="/login">Sign in</Link>
      </div>
    </main>
  );
}
