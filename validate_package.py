"""Validates the draft GNN data package against Doc 00 formats. Run: python validate_package.py [dir]"""
import json, re, sys, hashlib, csv, collections, datetime
D = sys.argv[1] if len(sys.argv) > 1 else "."
NODE_TYPES = {'Provision','Case','Holding','Court','TransactionType','ActorClass','ProcessFact','Standard','Source','Element'}
EDGE_TYPES = {'cites','interprets','follows','distinguishes','limits','overrules','superseded_by_statute','applies_to','binds','satisfies','published_by','addresses','next_version','amends'}
TX = {'going_private','other_controller_deal','third_party_sale','interested_director','other'}
AC = {'controller','control_group','independent_director','interested_director','disinterested_stockholder','minority_stockholder'}
FACT_KEYS = {'transaction_type','controller_present','controller_identity','signing_date','announcement_date','closing_date','litigation_commenced_on',
 'interested_director_involved','special_committee_formed','committee_all_disinterested','committee_power_to_say_no','committee_power_to_negotiate',
 'committee_free_to_select_advisors','committee_duty_of_care_met','committee_formed_before_substantive_negotiation','committee_approval_obtained',
 'mom_condition_in_agreement','mom_vote_informed','mom_vote_uncoerced','mom_approval_obtained','disinterested_stockholder_approval_obtained',
 'disinterested_director_approval_obtained','deal_value_usd'}
OPS = ('eq','ne','in','lt','lte','gt','gte')
SLUG = re.compile(r'^[a-z0-9][a-z0-9._@-]*$')
errs = []
def err(m): errs.append(m)
def pdate(s, ctx):
    try: return datetime.date.fromisoformat(s)
    except Exception: err(f"bad date {s!r} in {ctx}")
def vpred(p, ctx):
    if p is None: return
    if 'const' in p: return
    for k in ('all','any'):
        if k in p:
            for c in p[k]: vpred(c, ctx)
            return
    if 'not' in p: return vpred(p['not'], ctx)
    if 'fact' in p:
        if p['fact'] not in FACT_KEYS: err(f"unknown fact key {p['fact']} in {ctx}")
        if len([o for o in OPS if o in p]) != 1: err(f"need exactly one operator in {ctx}: {p}")
        return
    err(f"malformed predicate in {ctx}: {p}")
g = json.load(open(f"{D}/03_training_graph.json"))
nodes = {n['node_id']: n for n in g['nodes']}
if len(nodes) != len(g['nodes']): err("duplicate node ids")
FRAME_KEYS = {'addressee_classes','transaction_types','applies_when','exceptions','non_application','defined_terms','jurisdiction','valid_from','valid_to','source_spans','audited'}
NODE_KEYS = {'node_id','node_type','label','props','scope_frame','valid_from','valid_to','known_from','source_ids','origin','audited'}
EDGE_KEYS = {'edge_id','src','dst','edge_type','condition','props','valid_from','valid_to','known_from','source_span','confidence','origin','audited'}
for nid, n in nodes.items():
    if set(n) != NODE_KEYS: err(f"node keys mismatch {nid}")
    t, _, slug = nid.partition(':')
    if t != n['node_type'] or t not in NODE_TYPES: err(f"type/prefix mismatch {nid}")
    if not SLUG.match(slug): err(f"bad slug {nid}")
    pdate(n['known_from'], nid)
    for k in ('valid_from','valid_to'):
        if n[k]: pdate(n[k], nid)
    fr = n['scope_frame']
    if n['node_type'] in ('Provision','Holding') and fr is None: err(f"{nid} lacks scope frame (rule_candidates would drop it)")
    if fr:
        if set(fr) != FRAME_KEYS: err(f"frame keys mismatch {nid}")
        for a in fr['addressee_classes']:
            if a not in AC: err(f"bad addressee {a} {nid}")
        for t2 in fr['transaction_types']:
            if t2 not in TX: err(f"bad transaction type {t2} {nid}")
        vpred(fr['applies_when'], nid); vpred(fr['non_application'], nid)
    for pk in ('safe_harbor_when','bjr_when','met_when','unmet_when'):
        if pk in n['props']: vpred(n['props'][pk], f"{nid}.{pk}")
    if n['audited'] or n['origin'] == 'seed': err(f"{nid} must be unaudited llm_extracted in this draft")
seen = set(); applies = collections.defaultdict(lambda: {'tx': set(), 'ac': set()})
for e in g['edges']:
    if set(e) != EDGE_KEYS: err(f"edge keys mismatch {e.get('edge_id')}")
    want = "edge_" + hashlib.sha256(f"{e['src']}|{e['dst']}|{e['edge_type']}".encode()).hexdigest()[:16]
    if e['edge_id'] != want: err(f"edge id mismatch {e['edge_id']}")
    if e['edge_id'] in seen: err(f"duplicate edge {e['edge_id']}")
    seen.add(e['edge_id'])
    if e['edge_type'] not in EDGE_TYPES: err(f"bad edge type {e['edge_type']}")
    for end in ('src','dst'):
        if e[end] not in nodes: err(f"edge {e['edge_id']} dangling {end} {e[end]}")
    pdate(e['known_from'], e['edge_id']); vpred(e['condition'], e['edge_id'])
    if e['src'] in nodes and e['dst'] in nodes:
        if e['known_from'] < max(nodes[e['src']]['known_from'], nodes[e['dst']]['known_from']) and e['edge_type'] != 'satisfies':
            err(f"edge {e['src']}->{e['dst']} known_from earlier than an endpoint")
    if e['edge_type'] == 'applies_to':
        d = e['dst']
        (applies[e['src']]['tx'] if d.startswith('TransactionType:') else applies[e['src']]['ac']).add(d.split(':')[1])
for nid, n in nodes.items():
    fr = n['scope_frame']
    if fr and n['node_type'] in ('Provision','Holding') and nid in applies:
        if set(fr['transaction_types']) != applies[nid]['tx']: err(f"{nid}: frame transaction_types disagree with applies_to edges")
        if set(fr['addressee_classes']) != applies[nid]['ac']: err(f"{nid}: frame addressee_classes disagree with applies_to edges")
labels = [json.loads(l) for l in open(f"{D}/04_labels.jsonl")]
lt = set()
for r in labels:
    for k in ('src','dst'):
        if r[k] not in nodes: err(f"label {r['label_id']} unknown node {r[k]}")
    if r['edge_type'] not in EDGE_TYPES: err(f"label {r['label_id']} bad edge type")
    key = (r['edge_type'], r['src'], r['dst'])
    if key in lt: err(f"duplicate label {key}")
    lt.add(key)
pos = {(r['edge_type'], r['src'], r['dst']) for r in labels if r['label'] == 'positive'}
for r in labels:
    if r['label'] == 'negative' and (r['edge_type'], r['src'], r['dst']) in {(e['edge_type'], e['src'], e['dst']) for e in g['edges']}:
        err(f"negative label {r['label_id']} contradicts a graph edge")
for e in g['edges']:
    if e['edge_type'] in ('cites','addresses','applies_to') and (e['edge_type'], e['src'], e['dst']) not in pos: err(f"edge without positive label {e['edge_id']}")
bench = [json.loads(l) for l in open(f"{D}/06_failure_benchmark.jsonl")]
ids = [b['case_id'] for b in bench]
if len(ids) != len(set(ids)): err("duplicate benchmark ids")
for b in bench:
    a = b['claim']['authority_node_id']
    if a and b['coverage_status'] == 'in_graph' and a not in nodes: err(f"{b['case_id']} authority {a} not in graph but marked in_graph")
    if a and b['coverage_status'] in ('fabricated_fictional','real_not_ingested') and a in nodes: err(f"{b['case_id']} authority exists in graph but marked {b['coverage_status']}")
    e = b['claim']['element_node_id']
    if e and e not in nodes: err(f"{b['case_id']} unknown element {e}")
    for k, v in b['matter']['facts'].items():
        if k not in FACT_KEYS: err(f"{b['case_id']} bad fact key {k}")
    if b['split'] not in ('train','val','test'): err(f"{b['case_id']} bad split")
sig = collections.defaultdict(set)
for b in bench:
    sig[(b['claim']['authority_node_id'], b['claim']['element_node_id'], b['failure_type'])].add(b['split'])
for k, s in sig.items():
    if len(s) > 1: err(f"benchmark signature {k} appears in several splits {s}")
with open(f"{D}/05_opinion_to_element.csv") as f:
    rows = list(csv.DictReader(f))
for r in rows:
    if r['authority_node_id'] not in nodes or r['element_or_standard_node_id'] not in nodes: err(f"mapping row dangling: {r}")
try:
    import yaml
    y = yaml.safe_load(open(f"{D}/02_source_list.yaml"))
    for en in y['entries']:
        if en.get('terms_verified') is not False: err(f"{en['entry_id']}: terms_verified must be false until a human verifies")
except ImportError:
    print("(pyyaml not installed; skipped YAML check)")
except FileNotFoundError:
    err("02_source_list.yaml missing")
print(f"nodes={len(nodes)} edges={len(g['edges'])} labels={len(labels)} (pos={len(pos)}) mapping={len(rows)} benchmark={len(bench)}")
print("splits:", dict(collections.Counter(b['split'] for b in bench)))
print("label tiers:", dict(collections.Counter((r['label'], r['negative_tier']) for r in labels)))
if errs:
    print(f"\n{len(errs)} PROBLEM(S):"); [print(" -", m) for m in errs]; sys.exit(1)
print("OK: structural checks passed (this is NOT legal review)")
