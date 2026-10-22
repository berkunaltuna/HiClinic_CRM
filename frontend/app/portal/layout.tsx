export const metadata = {
  title: "Secure photo upload",
  // Portal links are private: keep them out of search engines and Referer headers.
  robots: { index: false, follow: false },
  referrer: "no-referrer" as const,
};

export default function PortalLayout({ children }: { children: React.ReactNode }) {
  return <main>{children}</main>;
}
