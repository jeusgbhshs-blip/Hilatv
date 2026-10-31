/** Placeholder for a route that is not built yet. No sample rows, no stock photos. */
export function BuildingPage({ title, note }: { title: string; note: string }) {
  return (
    <div className="mx-auto w-full max-w-195">
      <h1 className="text-h1 font-medium tracking-wide">{title}</h1>
      <p className="mt-3 text-body text-text-2">建设中</p>
      <p className="mt-2 max-w-xl text-small text-text-3">{note}</p>
    </div>
  );
}
