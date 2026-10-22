import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Link, Route, Routes, useLocation } from "react-router-dom";

import { Loading } from "./components/bits";
import Shell from "./components/Shell";
import { SessionProvider } from "./lib/session";
import Desk from "./pages/Desk";

const Cases = lazy(() => import("./pages/Cases"));
const CaseFile = lazy(() => import("./pages/CaseFile"));
const Referral = lazy(() => import("./pages/Referral"));
const Suggestions = lazy(() => import("./pages/Suggestions"));
const Reports = lazy(() => import("./pages/Reports"));
const ReportPage = lazy(() => import("./pages/Reports").then((m) => ({ default: m.ReportPage })));
const Identifiers = lazy(() => import("./pages/Identifiers"));
const IdentifierPage = lazy(() => import("./pages/Identifiers").then((m) => ({ default: m.IdentifierPage })));
const Ask = lazy(() => import("./pages/Ask"));
const Audit = lazy(() => import("./pages/Audit"));
const AddReports = lazy(() => import("./pages/AddReports"));
const Quality = lazy(() => import("./pages/Quality"));
const About = lazy(() => import("./pages/About"));
const Alerts = lazy(() => import("./pages/Alerts"));
const SignIn = lazy(() => import("./pages/SignIn"));

function ScrollTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

function NotFound() {
  return (
    <div className="narrow">
      <h1>Nothing here</h1>
      <p>This address does not match a page. <Link to="/">Go to the desk</Link> or press Ctrl K to find a case.</p>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <SessionProvider>
        <ScrollTop />
        <Routes>
          <Route path="/cases/:id/referral" element={<Suspense fallback={<Loading />}><Referral /></Suspense>} />
          <Route path="*" element={
            <Shell>
              <Suspense fallback={<Loading />}>
                <Routes>
                  <Route path="/" element={<Desk />} />
                  <Route path="/cases" element={<Cases />} />
                  <Route path="/cases/:id" element={<CaseFile />} />
                  <Route path="/suggestions" element={<Suggestions />} />
                  <Route path="/suggestions/:id" element={<Suggestions />} />
                  <Route path="/reports" element={<Reports />} />
                  <Route path="/reports/:id" element={<ReportPage />} />
                  <Route path="/identifiers" element={<Identifiers />} />
                  <Route path="/identifiers/:id" element={<IdentifierPage />} />
                  <Route path="/ask" element={<Ask />} />
                  <Route path="/audit" element={<Audit />} />
                  <Route path="/add" element={<AddReports />} />
                  <Route path="/quality" element={<Quality />} />
                  <Route path="/about" element={<About />} />
                  <Route path="/alerts" element={<Alerts />} />
                  <Route path="/sign-in" element={<SignIn />} />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </Shell>
          } />
        </Routes>
      </SessionProvider>
    </BrowserRouter>
  );
}
