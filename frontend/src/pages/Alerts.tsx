import { Link } from "react-router-dom";

import { api, type Alert, type Emerging } from "../api";
import { Empty, ErrorBox, Loading, PageHead, ReportRef } from "../components/bits";
import { plural, when } from "../lib/format";
import { useSession } from "../lib/session";
import { useApi } from "../lib/useApi";

const KIND: Record<string, string> = {
  watchlist: "Watchlist", duplicate: "Possible repeat", joined_case: "New report on an active case",
};

export default function Alerts() {
  const { can, toast } = useSession();
  const { data, error, reload, setData } = useApi<{ alerts: Alert[]; emerging: Emerging[] }>("/api/alerts");
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading />;
  async function seen(id: number) {
    try {
      await api.post(`/api/alerts/${id}/seen`);
    } catch (e) {
      toast((e as Error).message, "bad");
      return;
    }
    setData({ ...data!, alerts: data!.alerts.map((a) => (a.id === id ? { ...a, seen: true } : a)) });
  }
  return (
    <div className="narrow">
      <PageHead title="Alerts" lead="Raised when a watched identifier turns up, a report looks like a repeat, or a new report joins a case someone is already working on." />
      {data.emerging.length > 0 && (
        <section className="panel">
          <h2>Growing fast</h2>
          <ul className="plain">
            {data.emerging.map((e) => <li key={e.case_id}><Link to={`/cases/${e.case_id}`} className="id id--link">{e.case_id}</Link> {plural(e.recent, "report")} in the last {e.days} days, {e.earlier} before.</li>)}
          </ul>
        </section>
      )}
      {data.alerts.length === 0 ? <Empty>No alerts. Put an identifier on the watchlist, or add a report to an approved case, to see one.</Empty> : (
        <ul className="alerts">
          {data.alerts.map((a) => (
            <li key={a.id} className={a.seen ? "alerts__item is-seen" : "alerts__item"}>
              <p><span className="tag">{KIND[a.kind] ?? a.kind}</span> {a.message}</p>
              <p className="tiny">
                {when(a.created_at)}
                {a.case_id && <> <Link to={`/cases/${a.case_id}`}>Open {a.case_id}</Link></>}
                {a.report_id && <> <ReportRef id={a.report_id} /></>}
                {!a.seen && can("analyst") && <> <button className="linkbtn" onClick={() => seen(a.id)}>Mark as seen</button></>}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
