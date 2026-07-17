import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, inr } from "../api.js";

const PRIMARY = "#2a78d6";
const GRID = "#ececea";
const MUTED = "#8a8a8a";

const RULE_LABELS = {
  DUPLICATE_INVOICE: "Duplicate invoice",
  AMOUNT_OUTLIER: "Amount outlier",
  MISSING_FIELD: "Missing field",
  DATE_INCONSISTENT: "Date inconsistent",
  CATEGORY_MISMATCH: "Category mismatch",
};

const axis = { stroke: MUTED, fontSize: 12, tickLine: false, axisLine: { stroke: GRID } };

function Chart({ title, children }) {
  return (
    <section className="panel">
      <h2>{title}</h2>
      <ResponsiveContainer width="100%" height={240}>
        {children}
      </ResponsiveContainer>
    </section>
  );
}

export default function Overview({ version }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([api.summary(), api.trends(), api.breakdown("vendor"), api.breakdown("category")])
      .then(([summary, trends, vendors, categories]) =>
        setData({ summary, monthly: trends.monthly, vendors: vendors.rows, categories: categories.rows })
      )
      .catch((e) => setError(e.message));
  }, [version]);

  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="empty">Loading…</p>;

  const { summary, monthly, vendors, categories } = data;
  const rules = Object.entries(summary.anomalies_by_rule || {}).map(([rule, count]) => ({
    rule: RULE_LABELS[rule] || rule,
    count,
  }));

  return (
    <>
      <div className="stats">
        <div className="stat">
          <div className="label">Documents processed</div>
          <div className="value">{summary.total_documents}</div>
        </div>
        <div className="stat">
          <div className="label">Documents flagged</div>
          <div className="value">{summary.flagged_documents}</div>
        </div>
        <div className="stat">
          <div className="label">Anomalies</div>
          <div className="value">{summary.total_anomalies}</div>
        </div>
        <div className="stat">
          <div className="label">Total spend</div>
          <div className="value">₹{inr(summary.total_spend)}</div>
        </div>
      </div>

      {monthly.length > 0 && (
        <div className="grid-2">
          <Chart title="Monthly spend">
            <LineChart data={monthly} margin={{ left: 12, right: 8, top: 4 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" {...axis} />
              <YAxis {...axis} tickFormatter={(v) => `${v / 100000}L`} width={36} />
              <Tooltip formatter={(v) => [`₹${inr(v)}`, "Spend"]} />
              <Line dataKey="total" stroke={PRIMARY} strokeWidth={2} dot={{ r: 3, fill: PRIMARY }} />
            </LineChart>
          </Chart>
          <Chart title="Documents flagged per month">
            <BarChart data={monthly} margin={{ left: 12, right: 8, top: 4 }}>
              <CartesianGrid stroke={GRID} vertical={false} />
              <XAxis dataKey="month" {...axis} />
              <YAxis {...axis} allowDecimals={false} width={36} />
              <Tooltip formatter={(v) => [v, "Flagged"]} />
              <Bar dataKey="flagged" fill={PRIMARY} radius={[4, 4, 0, 0]} maxBarSize={28} />
            </BarChart>
          </Chart>
        </div>
      )}

      <div className="grid-2">
        <Chart title="Spend by category">
          <BarChart data={categories} layout="vertical" margin={{ left: 40, right: 8 }}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" {...axis} tickFormatter={(v) => `${v / 100000}L`} />
            <YAxis type="category" dataKey="key" {...axis} width={110} />
            <Tooltip formatter={(v) => [`₹${inr(v)}`, "Spend"]} />
            <Bar dataKey="total_spend" fill={PRIMARY} radius={[0, 4, 4, 0]} maxBarSize={22} />
          </BarChart>
        </Chart>
        <Chart title="Anomalies by rule">
          <BarChart data={rules} layout="vertical" margin={{ left: 40, right: 8 }}>
            <CartesianGrid stroke={GRID} horizontal={false} />
            <XAxis type="number" {...axis} allowDecimals={false} />
            <YAxis type="category" dataKey="rule" {...axis} width={130} />
            <Tooltip formatter={(v) => [v, "Count"]} />
            <Bar dataKey="count" fill={PRIMARY} radius={[0, 4, 4, 0]} maxBarSize={22} />
          </BarChart>
        </Chart>
      </div>

      <section className="panel" style={{ marginTop: 16 }}>
        <h2>Vendors</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Vendor</th>
                <th className="num">Documents</th>
                <th className="num">Total spend (₹)</th>
                <th className="num">Anomalies</th>
              </tr>
            </thead>
            <tbody>
              {vendors.map((v) => (
                <tr key={v.key}>
                  <td>{v.key}</td>
                  <td className="num">{v.documents}</td>
                  <td className="num">{inr(v.total_spend)}</td>
                  <td className="num">{v.anomalies}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
