import { NavLink, Route, Routes } from "react-router-dom";

import { appConfig } from "./config";

type PlaceholderPageProps = {
  eyebrow: string;
  title: string;
  description: string;
};

const routes = [
  { path: "/", label: "Home" },
  { path: "/league", label: "League" },
  { path: "/managers", label: "Managers" },
  { path: "/draft", label: "Draft" },
];

function PlaceholderPage({ eyebrow, title, description }: PlaceholderPageProps) {
  return (
    <section className="panel route-panel" aria-labelledby={`${eyebrow}-title`}>
      <p className="eyebrow">{eyebrow}</p>
      <h1 id={`${eyebrow}-title`}>{title}</h1>
      <p>{description}</p>
      <div className="placeholder-card">
        <span>Coming next</span>
        <strong>Data-backed fantasy history without live dashboard recomputation.</strong>
      </div>
    </section>
  );
}

function Home() {
  return (
    <main className="hero">
      <section className="hero-copy" aria-labelledby="home-title">
        <p className="eyebrow">ESPN fantasy football analytics</p>
        <h1 id="home-title">League-specific intelligence for draft prep and league history.</h1>
        <p>
          LeagueBrief will import ESPN league history once, persist versioned analytics, and turn
          years of matchups, managers, drafts, and trends into fast dashboard views.
        </p>
        <div className="hero-actions">
          <NavLink className="button primary" to="/league">
            Preview league shell
          </NavLink>
          <a className="button secondary" href={`${appConfig.apiBaseUrl}/health`}>
            API health
          </a>
        </div>
      </section>

      <aside className="panel status-card" aria-label="MVP shell status">
        <p className="eyebrow">Phase 2 shell</p>
        <ul>
          <li>Google and Microsoft auth placeholders only</li>
          <li>No database, ESPN, or Key Vault calls yet</li>
          <li>Static Web Apps + Front Door deployment-ready</li>
        </ul>
      </aside>
    </main>
  );
}

function NotFound() {
  return (
    <section className="panel route-panel" aria-labelledby="not-found-title">
      <p className="eyebrow">404</p>
      <h1 id="not-found-title">Page not found.</h1>
      <p>The LeagueBrief shell only includes the MVP placeholder routes for now.</p>
      <NavLink className="button primary" to="/">
        Back home
      </NavLink>
    </section>
  );
}

function App() {
  return (
    <div className="app-shell">
      <header className="site-header">
        <NavLink className="brand" to="/" aria-label="LeagueBrief home">
          <span className="brand-mark">LB</span>
          <span>LeagueBrief</span>
        </NavLink>
        <nav aria-label="Primary navigation">
          {routes.map((route) => (
            <NavLink
              className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
              end={route.path === "/"}
              key={route.path}
              to={route.path}
            >
              {route.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<Home />} />
        <Route
          path="/league"
          element={
            <PlaceholderPage
              eyebrow="League overview"
              title="League overview"
              description="Historical standings, champions, rivalry notes, and league-level trends will live here."
            />
          }
        />
        <Route
          path="/managers"
          element={
            <PlaceholderPage
              eyebrow="Manager analysis"
              title="Manager analysis"
              description="Manager profiles, all-time records, luck, consistency, and long-term performance will live here."
            />
          }
        />
        <Route
          path="/draft"
          element={
            <PlaceholderPage
              eyebrow="Draft room"
              title="Draft analytics"
              description="Draft reach tendencies, historical pick value, and FantasyPros comparison views will live here."
            />
          }
        />
        <Route path="*" element={<NotFound />} />
      </Routes>

      <footer className="site-footer">
        <span>LeagueBrief MVP shell</span>
        <span>Support link placeholder</span>
      </footer>
    </div>
  );
}

export default App;
