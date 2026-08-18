"""Render the ledger as a single self-contained HTML page.

A projection layer only: reads receipts / certs / mints / ores, writes
nothing, decides nothing. The page is a snapshot of the physical history of
intelligence recorded on this node — Constitution IV made visible.
"""

import html
import json
import math

CSS = """
body{background:#0b0e13;color:#d6dae2;font-family:'SF Mono',Menlo,monospace;
     margin:0;padding:2.5rem 1.5rem;line-height:1.55}
main{max-width:960px;margin:0 auto}
h1{font-size:1.6rem;letter-spacing:.14em;color:#e8ecf4;margin:0}
h2{font-size:.95rem;letter-spacing:.22em;color:#7ee0a3;margin:2.6rem 0 .7rem;
   text-transform:uppercase}
p.tag{color:#8a93a6;font-size:.82rem;margin:.4rem 0 0}
table{border-collapse:collapse;width:100%;font-size:.8rem;margin:.5rem 0}
th,td{padding:.28rem .6rem;text-align:left;border-bottom:1px solid #1c2230}
th{color:#8a93a6;font-weight:normal}
td.n{text-align:right;font-variant-numeric:tabular-nums}
.star{color:#ffd166}.dim{color:#5b6372}.mint{color:#7ee0a3}
.ore{color:#c9a7ff}.warn{color:#e0876a}
.svgbox{overflow-x:auto;background:#0e1219;border:1px solid #1c2230;
        border-radius:6px;padding:.6rem;margin:.6rem 0}
footer{margin-top:3rem;color:#5b6372;font-size:.72rem}
"""


def _svg_pareto(certs):
    """Success rate (y) vs J/success (x, log) — the shape of a frontier."""
    pts = [c for c in certs if c["successes"] > 0]
    if not pts:
        return ""
    w, h, pad = 640, 260, 46
    xs = [math.log10(max(c["total_j"] / c["successes"], 0.01)) for c in pts]
    x0, x1 = min(xs) - 0.3, max(xs) + 0.3
    out = [f'<svg viewBox="0 0 {w} {h}" width="100%" '
           f'xmlns="http://www.w3.org/2000/svg" font-family="monospace">']
    for frac in (0, 0.5, 1.0):
        y = h - pad - (h - 2 * pad) * frac
        out.append(f'<line x1="{pad}" y1="{y:.0f}" x2="{w-pad}" y2="{y:.0f}" '
                   'stroke="#1c2230"/>')
        out.append(f'<text x="6" y="{y+4:.0f}" fill="#5b6372" font-size="10">'
                   f'{int(frac*100)}%</text>')
    for c, lx in zip(pts, xs):
        x = pad + (w - 2 * pad) * (lx - x0) / (x1 - x0)
        y = h - pad - (h - 2 * pad) * c["success_rate"]
        color = "#ffd166" if c.get("_frontier") else "#4d78cc"
        jps = c["total_j"] / c["successes"]
        label = f'{c["runner_id"]} {jps:.1f}J'
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="{color}"/>')
        out.append(f'<text x="{x+8:.0f}" y="{y+4:.0f}" fill="#8a93a6" '
                   f'font-size="10">{html.escape(label)}</text>')
    out.append(f'<text x="{w/2:.0f}" y="{h-8}" fill="#5b6372" font-size="10" '
               'text-anchor="middle">J per verified success (log) →</text>')
    out.append("</svg>")
    return '<div class="svgbox">' + "".join(out) + "</div>"


def build_html(conn) -> str:
    import eligibility

    n_receipts = conn.execute("SELECT COUNT(*) c FROM receipts").fetchone()["c"]
    n_mints = conn.execute("SELECT COUNT(*) c FROM mints").fetchone()["c"]
    gain = conn.execute(
        "SELECT COALESCE(SUM(certified_gain_j),0) s FROM mints").fetchone()["s"]
    hw = conn.execute(
        "SELECT COUNT(DISTINCT json_extract(receipt_json,"
        "'$.hardware_profile.platform')) c FROM receipts").fetchone()["c"]

    parts = [f"<style>{CSS}</style><main>",
             "<h1>EDEN — ledger</h1>",
             '<p class="tag">a record of what intelligence made unnecessary '
             f"&middot; {n_receipts} receipts &middot; {n_mints} simulated "
             f"mints (+{gain:.1f}) &middot; {hw} hardware nodes</p>"]

    # Distribution frontiers (challenge families)
    fams = conn.execute(
        "SELECT DISTINCT family_id FROM distribution_certs").fetchall()
    for f in fams:
        fam = f["family_id"]
        rows = conn.execute(
            "SELECT * FROM distribution_certs WHERE family_id=? "
            "ORDER BY created_at", (fam,)).fetchall()
        certs = []
        for r in rows:
            c = dict(r)
            c["j_per_success"] = (c["j_per_success"] if c["j_per_success"]
                                  is not None else float("inf"))
            c["rate_ci95"] = [c["rate_lo"], c["rate_hi"]]
            c["runner"] = c["runner_id"]
            c["code_hash"] = c["runner_code_hash"]
            certs.append(c)
        frontier = eligibility.pareto_frontier(certs)
        for c in certs:
            c["_frontier"] = c in frontier
        contract = conn.execute(
            "SELECT task_contract_version v FROM tasks WHERE family_id=? "
            "LIMIT 1", (fam,)).fetchone()
        parts.append(f"<h2>frontier — {html.escape(contract['v'])} "
                     f"<span class='dim'>{fam}</span></h2>")
        parts.append(_svg_pareto(certs))
        parts.append("<table><tr><th></th><th>strategy</th><th>meter</th>"
                     "<th>success</th><th>ci95</th><th>J/success</th></tr>")
        for c in sorted(certs, key=lambda c: -c["success_rate"]):
            star = '<span class="star">★</span>' if c["_frontier"] else ""
            jps = ("∞" if c["j_per_success"] == float("inf")
                   else f"{c['j_per_success']:.2f}")
            parts.append(
                f"<tr><td>{star}</td><td>{html.escape(c['runner_id'])}</td>"
                f"<td class='dim'>{html.escape(c['meter'])}</td>"
                f"<td class='n'>{c['successes']}/{c['attempts']}</td>"
                f"<td class='n dim'>[{c['rate_lo']*100:.0f},"
                f"{c['rate_hi']*100:.0f}]%</td>"
                f"<td class='n'>{jps}</td></tr>")
        parts.append("</table>")

    # Mint history
    parts.append("<h2>mints (simulated)</h2><table>"
                 "<tr><th>#</th><th>dethroned</th><th>new record</th>"
                 "<th>gain</th></tr>")
    for m in conn.execute("SELECT * FROM mints ORDER BY mint_id"):
        parts.append(
            f"<tr><td class='dim'>{m['mint_id']}</td>"
            f"<td class='dim'>{html.escape(m['prev_group'][:44])}</td>"
            f"<td>{html.escape(m['new_group'][:44])}</td>"
            f"<td class='n mint'>+{m['certified_gain_j']:.3f}</td></tr>")
    parts.append("</table>")

    # Ores
    ores = conn.execute(
        "SELECT o.*, r.receipt_json FROM ores o JOIN receipts r "
        "ON r.receipt_id=o.receipt_id ORDER BY o.zero_bits DESC").fetchall()
    parts.append("<h2>ores — the cultural layer</h2>")
    if not ores:
        parts.append('<p class="dim">none discovered yet</p>')
    else:
        parts.append("<table><tr><th>tier</th><th>rarity</th><th>origin</th>"
                     "<th>hash</th></tr>")
        for o in ores:
            rec = json.loads(o["receipt_json"])
            parts.append(
                f"<tr><td class='ore'>{o['tier']}</td>"
                f"<td class='n'>~1/{2**o['zero_bits']}</td>"
                f"<td>{html.escape(rec['runner_id'])} "
                f"<span class='dim'>({rec['run_energy']['energy_joules']:.2f} J"
                f")</span></td>"
                f"<td class='dim'>{o['ore_hash'][:20]}…</td></tr>")
        parts.append("</table>")

    parts.append("<footer>EDEN mints on observed dominance, not counterfactual "
                 "savings. Receipts are immutable observations; this page is a "
                 "versioned interpretation.<br>"
                 "github.com/ozoz5/eden-network &middot; Apache-2.0</footer>")
    parts.append("</main>")
    return ("<!doctype html><meta charset='utf-8'>"
            "<title>EDEN ledger</title>" + "".join(parts))
