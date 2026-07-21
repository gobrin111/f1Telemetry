const plannedCapabilities = [
  "Import completed race sessions through FastF1",
  "Score eligible laps for unusual performance patterns",
  "Explain the features behind each anomaly score",
  "Compare timing and telemetry traces in the browser",
];

export default function Home() {
  return (
    <main>
      <section className="hero" aria-labelledby="page-title">
        <p className="eyebrow">F1 telemetry analysis</p>
        <h1 id="page-title">Find the laps that deserve a closer look.</h1>
        <p className="lede">
          A browser-based workspace for detecting and explaining unusual Formula 1 race
          performance. The project foundation is ready; session analysis arrives in the
          next milestones.
        </p>
        <div className="status" role="status">
          <span aria-hidden="true" />
          Phase 5 · PostgreSQL storage
        </div>
      </section>

      <section className="capabilities" aria-labelledby="capabilities-title">
        <div>
          <p className="eyebrow">MVP workflow</p>
          <h2 id="capabilities-title">From race data to evidence</h2>
        </div>
        <ol>
          {plannedCapabilities.map((capability, index) => (
            <li key={capability}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              {capability}
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}
