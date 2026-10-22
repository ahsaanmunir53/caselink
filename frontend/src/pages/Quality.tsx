import type { Pairwise, Quality as Q } from "../api";
import { Empty, ErrorBox, Loading, PageHead } from "../components/bits";
import { ENTITY_LABEL, pct } from "../lib/format";
import { useApi } from "../lib/useApi";

function Row({ name, what, p }: { name: string; what: string; p: Pairwise }) {
  return (
    <tr>
      <th scope="row"><span className="rowname">{name}</span><span className="tiny">{what}</span></th>
      <td className="num">{pct(p.precision)}</td>
      <td className="num">{pct(p.recall)}</td>
      <td className="num">{pct(p.f1)}</td>
      <td className="num">{p.pairs_correct.toLocaleString("en")} of {p.pairs_predicted.toLocaleString("en")}</td>
    </tr>
  );
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div className="meter">
      <span className="meter__label">{label}</span>
      <span className="meter__track"><span className="meter__fill" style={{ width: `${value * 100}%` }} /></span>
      <span className="meter__value">{pct(value)}</span>
    </div>
  );
}

export default function Quality() {
  const { data, error, reload } = useApi<Q>("/api/quality");
  if (error) return <ErrorBox error={error} retry={reload} />;
  if (!data) return <Loading label="Scoring the linker" />;
  if (!data.available) return <Empty>{data.reason}</Empty>;
  const d = data;
  return (
    <div className="narrow">
      <PageHead title="How well it links" lead={`The demo data was generated with a hidden answer key: ${d.dataset.operations} fraud operations behind ${d.dataset.reports - d.dataset.one_off_reports} reports, plus ${d.dataset.one_off_reports} one-off reports that belong to nothing. These scores compare CaseLink's grouping with that key.`} />

      <section className="panel">
        <h2>Grouping</h2>
        <p className="panel__lead">
          Scored on pairs of reports. Precision: of the pairs CaseLink put together, how many really belong together. Recall: of the pairs that belong together, how many CaseLink found.
          A wrong join can send police after the wrong person, so the rules are tuned for precision and leave the doubtful ones to people.
        </p>
        <div className="meters">
          <Meter label="Rules alone, precision" value={d.rules_only.precision} />
          <Meter label="Rules alone, recall" value={d.rules_only.recall} />
          <Meter label="With suggestions accepted, recall" value={d.rules_plus_suggestions.recall} />
        </div>
        <div className="tablewrap">
          <table className="table">
            <thead><tr><th scope="col">Grouping</th><th scope="col" className="num">Precision</th><th scope="col" className="num">Recall</th><th scope="col" className="num">F1</th><th scope="col" className="num">Right pairs</th></tr></thead>
            <tbody>
              <Row name="Rules alone" what="What the linker joins by itself: shared phone numbers, accounts, websites, emails, licences, handles." p={d.rules_only} />
              <Row name="Rules and suggestions" what="If an analyst accepted every suggestion scoring 0.5 or more." p={d.rules_plus_suggestions} />
              <Row name="Cases right now" what="The cases as they stand, after the decisions people made in this demo." p={d.current_cases} />
            </tbody>
          </table>
        </div>
        <p className="small">
          Of {d.suggestions.total} suggestions, {d.suggestions.correct} point at reports from the same operation and {d.suggestions.wrong} do not.
          The wrong ones come from common agency names that unrelated agencies share, which is why they score low and wait for a person.
          {Object.keys(d.decisions).length ? ` So far in this demo: ${Object.entries(d.decisions).map(([k, v]) => `${v} ${k}`).join(", ")}.` : ""}
        </p>
      </section>

      <section className="panel">
        <h2>Reading identifiers</h2>
        <p className="panel__lead">Of the identifiers the generator wrote into the reports, in many formats (+92 300…, 0300-…, spaced IBANs, links without https), how many the rules found and normalised.</p>
        <div className="meters">
          <Meter label="Found (recall)" value={d.extraction.recall} />
          <Meter label="Correct (precision)" value={d.extraction.precision} />
        </div>
        <table className="table table--compact">
          <thead><tr><th scope="col">Kind</th><th scope="col" className="num">In the reports</th><th scope="col" className="num">Found</th></tr></thead>
          <tbody>
            {Object.entries(d.extraction.by_kind).map(([k, v]) => (
              <tr key={k}><th scope="row">{ENTITY_LABEL[k] ?? k}</th><td className="num">{v.injected}</td><td className="num">{v.found}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="panel">
        <h2>What these numbers do not show</h2>
        <ul className="steps">
          <li>The data is synthetic and the same code generated it, so real reports will be messier. Treat these as a regression test, not a promise.</li>
          <li>The same evaluation runs in CI on every change, with a gate that fails the build if precision or recall drops below set thresholds.</li>
          <li>AI second opinions and AI extraction are scored separately with <code>eval/run_eval.py --with-ai</code>, because they depend on which free model answered.</li>
        </ul>
      </section>
    </div>
  );
}
