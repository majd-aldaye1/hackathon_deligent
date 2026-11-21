"""Sanctions-screening identity engine, implementing Diligent's screening SOP (POLICY.md).

For every hit: resolve the customer (principles 2-3), build the verified picture of the
person (4), gather the hit's facts (5), clear only on a contradiction (6), confirm only on
agreement (7), compare names per principle 8, and cite the records used (9).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from . import text as T
from .data import Dataset, as_list, s

# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------
LISTING_PHRASES = {
    "sanctions": "a sanctioned individual",
    "pep": "a politically exposed person",
    "enforcement": "the subject of enforcement action",
    "adverse media": "named in adverse media",
    "soe": "a state-owned enterprise official",
}
OTHER_LISTING = "named on a watchlist"

CLEAR_TAIL = {
    "ENTITY_TYPE_MISMATCH": "A person and a company cannot be the same entity, so {hit} is cleared.",
    "DECEASED": "The listed person died before the customer was screened, so {hit} is not the customer.",
    "TEMPORAL_IMPOSSIBILITY": "The customer could not be the subject of that report, so {hit} is a different {kind}.",
    "DOB_MISMATCH": "No birth date the hit gives fits the customer, so {hit} is a different {kind}.",
    "NAME_MISMATCH_VERIFIED": "The verified legal name outranks the name on the customer record, so {hit} is a different {kind}.",
    "LOCATION_MISMATCH": "With no country in common, {hit} is a different {kind}.",
}


def hit_label(hf) -> str:
    return f"{hf.name} ({hf.hit_id})" if hf.name else hf.hit_id


def cap(x: str) -> str:
    return x[:1].upper() + x[1:] if x else x


def cap_sentences(sents: list, n: int) -> list:
    """At most n sentences: keep the first n-1 and the conclusion."""
    return sents if len(sents) <= n else sents[:n - 1] + sents[-1:]


CODE_PRIORITY = [
    "ENTITY_TYPE_MISMATCH", "DECEASED", "TEMPORAL_IMPOSSIBILITY", "DOB_MISMATCH",
    "NAME_MISMATCH_VERIFIED", "LOCATION_MISMATCH",
]

NEGATIVE_KYC = re.compile(
    r"\b(reject\w*|fail\w*|declin\w*|expired|unsuccessful|could not|unable to|not verified|not approved|"
    r"mismatch\w*|denied|invalid|fraudulent|suspended|revoked|pending|awaiting)\b", re.I)
KYC_HINT = re.compile(r"verif|identity|ID check|passport|driving licen|national ID|document|KYC|DOB|born|birth", re.I)
UPPER_TOKEN = re.compile(r"^[A-ZÀ-ÖØ-ÞĀ-ſ][A-ZÀ-ÖØ-ÞĀ-ſ'’\-\.]*$")
NOT_NAME_UPPER = {"ID", "DOB", "KYC", "UK", "US", "USA", "EU", "UAE", "AML", "SSN", "TIN", "N/A", "OK", "IBAN"}


_CITY_ALIASES = {
    "munchen": "munich", "koln": "cologne", "wien": "vienna", "praha": "prague", "lisboa": "lisbon", "roma": "rome",
    "milano": "milan", "firenze": "florence", "napoli": "naples", "venezia": "venice", "torino": "turin",
    "genova": "genoa", "warszawa": "warsaw", "kobenhavn": "copenhagen", "goteborg": "gothenburg",
    "bruxelles": "brussels", "brussel": "brussels", "den haag": "the hague", "zurich": "zurich", "geneve": "geneva",
    "moskva": "moscow", "kyiv": "kiev", "sevilla": "seville", "beograd": "belgrade", "athina": "athens",
    "bucuresti": "bucharest", "nurnberg": "nuremberg", "hannover": "hanover", "dacca": "dhaka", "bombay": "mumbai",
    "madras": "chennai", "calcutta": "kolkata", "frankfurt am main": "frankfurt", "krakow": "cracow",
    "antwerpen": "antwerp", "den bosch": "s-hertogenbosch", "porto": "oporto", "basel": "basle",
}


def city_alias(c: str) -> str:
    return _CITY_ALIASES.get(c, c)


def city_forms(city: str):
    """Folded spellings of a screened city: 'Spokane, WA' -> ['spokane'], 'München' -> ['munchen', 'munich']."""
    first = T.fold(city.split(",")[0]).strip()
    out = [first]
    if city_alias(first) != first:
        out.append(city_alias(first))
    for k, v in _CITY_ALIASES.items():
        if v == first and k not in out:
            out.append(k)
    return [x for x in out if x]


def norm_type(v: str) -> str:
    v = (v or "").strip().lower()
    if v.startswith(("comp", "org", "entity", "business", "corp", "legal")):
        return "Company"
    if v.startswith(("ind", "person", "natural", "human")):
        return "Individual"
    return v.title() if v else ""


def dob_parts_equal(a, b) -> bool:
    """Equal in every part both give."""
    if not a or not b:
        return True
    if a[0] != b[0]:
        return False
    if a[1] is not None and b[1] is not None and a[1] != b[1]:
        return False
    if a[1] is not None and b[1] is not None and a[2] is not None and b[2] is not None and a[2] != b[2]:
        return False
    return True


def dob_agrees(c, h) -> bool:
    return dob_parts_equal(c, h)


def dob_contradicts(c, h) -> bool:
    if abs(c[0] - h[0]) > 1:
        return True
    if c[0] == h[0] and c[1] is not None and h[1] is not None:
        if c[1] != h[1]:
            return True
        if c[2] is not None and h[2] is not None and c[2] != h[2]:
            return True
    return False


def max_age_at(dob, when) -> int:
    """Oldest the person can have been in the year of `when`: report year minus birth year.
    (Conservative: only clears when the customer was certainly under 16.)"""
    return when[0] - dob[0]


# ----------------------------------------------------------------------------
# Facts containers
# ----------------------------------------------------------------------------
@dataclass
class Check:
    id: str
    date: tuple
    name: str
    dob: tuple | None
    country: str | None
    doc_number: str = ""
    kind: str = "kyc"  # kyc | note


@dataclass
class Person:
    records: list
    entity_type: str
    record_names: list            # [(name, record_id)]
    verified: Check | None
    dob: tuple | None
    dob_src: str | None
    countries: dict               # country -> [source ids]
    approved_checks: list = field(default_factory=list)

    @property
    def primary(self):
        return self.records[0] if self.records else None


@dataclass
class HitFacts:
    hit_id: str
    entity_type: str
    name: str
    names: list
    dobs: list                    # [(date, source_label, source_id|None)]
    dob_origin: str               # 'listed' | 'profile notes' | 'search results' | ''
    countries: set
    earliest_report: tuple | None
    report_line: str
    deceased: tuple | None
    listing: str
    search_used: list


# ----------------------------------------------------------------------------
# Engine
# ----------------------------------------------------------------------------
class Engine:
    def __init__(self, ds: Dataset):
        self.ds = ds
        self._checks_cache: dict = {}
        self._notes_cache: dict = {}
        self._build_people()
        self._build_name_index()

    # ---------------------------- records & checks ---------------------------
    def rec(self, rid):
        return self.ds.cust_by_id.get(rid)

    def rec_type(self, rid):
        return norm_type(s(self.rec(rid).get("entity_type")))

    def rec_dob(self, rid):
        return T.parse_date(s(self.rec(rid).get("dob")), dayfirst=True)

    def kyc_checks(self, rid) -> list:
        """All KYC-provider checks reachable from a customer record via onboarding."""
        if rid in self._checks_cache:
            return self._checks_cache[rid]
        out, seen = [], set()
        for o in self.ds.onb_by_cust.get(rid, []):
            app = s(o.get("kyc_applicant_id"))
            for k in self.ds.kyc_by_app.get(app, []):
                kid = s(k.get("check_id"))
                if kid in seen:
                    continue
                seen.add(kid)
                out.append(k)
        self._checks_cache[rid] = out
        return out

    def approved_kyc(self, rid) -> list:
        out = []
        for k in self.kyc_checks(rid):
            res = s(k.get("result")).lower()
            if res not in ("approved", "passed", "clear", "verified", "success", "accepted"):
                continue
            d = T.parse_date(s(k.get("checked_at")), dayfirst=True)
            if not d:
                continue
            out.append(Check(
                id=s(k.get("check_id")), date=d, name=s(k.get("verified_name")),
                dob=T.parse_date(s(k.get("verified_dob")), dayfirst=True),
                country=T.norm_country(s(k.get("document_country"))),
                doc_number=s(k.get("document_number")), kind="kyc"))
        return out

    def notes(self, rid) -> list:
        e = s(self.rec(rid).get("email")).lower()
        return self.ds.notes_by_email.get(e, []) if e else []

    def note_checks_and_places(self, rid):
        """Approved identity checks recorded only in onboarding notes, and places the notes say
        the customer lived."""
        if rid in self._notes_cache:
            return self._notes_cache[rid]
        checks, places = [], []
        for n in self.notes(rid):
            nid = s(n.get("note_id"))
            txt = s(n.get("text"))
            ch = s(n.get("channel")).lower()
            created = T.parse_date(s(n.get("created_at")), dayfirst=True)
            parsed = None
            if ch == "kyc" or (KYC_HINT.search(txt) and re.search(r"\b(DOB|born|birth)\b", txt, re.I)):
                parsed = parse_kyc_note(txt, created)
            if parsed and not NEGATIVE_KYC.search(txt):
                name, dob, country, date = parsed
                checks.append(Check(id=nid, date=date or created, name=name, dob=dob, country=country, kind="note"))
            elif ch != "kyc":
                for c in T.find_countries(txt):
                    places.append((c, nid))
        self._notes_cache[rid] = (checks, places)
        return checks, places

    # ---------------------------- people (principle 3) -----------------------
    def _build_people(self):
        parent = {}

        def find(x):
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], parent[x])
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        by_phone_dob = defaultdict(list)
        for c in self.ds.customers:
            rid = s(c.get("record_id"))
            parent.setdefault(rid, rid)
            phone = re.sub(r"\D", "", s(c.get("phone")))
            d = T.parse_date(s(c.get("dob")), dayfirst=True)
            if phone and d and d[1] is not None and d[2] is not None:
                by_phone_dob[(phone, d)].append(rid)
        for rids in by_phone_dob.values():
            for r in rids[1:]:
                union(rids[0], r)
        # same document number on approved checks
        app2cust = defaultdict(set)
        for o in self.ds.onboarding:
            app2cust[s(o.get("kyc_applicant_id"))].add(s(o.get("customer_id")))
        by_doc = defaultdict(set)
        for k in self.ds.kyc:
            if s(k.get("result")).lower() != "approved":
                continue
            num = re.sub(r"\W", "", s(k.get("document_number"))).upper()
            if not num:
                continue
            for cid in app2cust.get(s(k.get("applicant_id")), ()):
                if cid in self.ds.cust_by_id:
                    by_doc[num].add(cid)
        for rids in by_doc.values():
            rids = sorted(rids)
            for r in rids[1:]:
                union(rids[0], r)
        groups = defaultdict(list)
        for rid in parent:
            groups[find(rid)].append(rid)
        self.person_of = {}
        for root, rids in groups.items():
            for r in rids:
                self.person_of[r] = root
        self.person_records = groups
        self._person_cache = {}

    def person_key(self, rid):
        return self.person_of.get(rid, rid)

    def record_names(self, rid) -> list:
        c = self.rec(rid)
        out = []
        full = s(c.get("full_name"))
        if full:
            out.append(full)
        pref = s(c.get("preferred_name"))
        if pref:
            parts = full.split()
            if len(T.name_parts(pref)) >= 2:
                out.append(pref)
            elif parts:
                out.append(pref + " " + parts[-1])
        ln = s(c.get("login_name"))
        if ln:
            out.append(ln)
        return out

    def person(self, first_rid) -> Person:
        """The full picture of the person a record belongs to; `first_rid` is listed first."""
        key = (self.person_key(first_rid), first_rid)
        if key in self._person_cache:
            return self._person_cache[key]
        rids = sorted(self.person_records.get(self.person_key(first_rid), [first_rid]))
        rids = [first_rid] + [r for r in rids if r != first_rid]
        names, countries = [], defaultdict(list)
        checks, places = [], []
        etype = ""
        for rid in rids:
            c = self.rec(rid)
            etype = etype or self.rec_type(rid)
            for n in self.record_names(rid):
                names.append((n, rid))
            for f in ("residence_country", "nationality"):
                for v in as_list(c.get(f)):          # a string, or a list (dual nationality)
                    cc = T.norm_country(s(v))
                    if cc and rid not in countries[cc]:
                        countries[cc].append(rid)
            checks.extend(self.approved_kyc(rid))
            nc, pl = self.note_checks_and_places(rid)
            checks.extend(nc)
            places.extend(pl)
        # unique checks
        uniq = {}
        for ch in checks:
            uniq.setdefault(ch.id, ch)
        checks = sorted(uniq.values(), key=lambda ch: (T.date_key_high(ch.date), ch.kind == "kyc"))
        verified = checks[-1] if checks else None
        if verified and verified.country:
            countries[verified.country].append(verified.id)
        # Older approved documents: a country only they give still ties the customer to it.
        # (Cautious reading: dropping it could turn a real link into a LOCATION_MISMATCH clear.)
        for ch in reversed(checks[:-1]):
            if ch.country and ch.country not in countries:
                countries[ch.country].append(ch.id)
        for cc, nid in places:
            if nid not in countries[cc]:
                countries[cc].append(nid)
        dob, dob_src = None, None
        dated = [ch for ch in checks if ch.dob]
        if dated:  # most recent approved check that states a date of birth
            dob, dob_src = dated[-1].dob, dated[-1].id
        else:
            for rid in rids:
                d = self.rec_dob(rid)
                if d:
                    dob, dob_src = d, rid
                    break
        p = Person(records=rids, entity_type=etype, record_names=names, verified=verified,
                   dob=dob, dob_src=dob_src, countries=dict(countries), approved_checks=checks)
        self._person_cache[key] = p
        return p

    # ---------------------------- resolution (principle 2) -------------------
    def _build_name_index(self):
        self.vocab = defaultdict(set)
        for c in self.ds.customers:
            rid = s(c.get("record_id"))
            comp = self.rec_type(rid) == "Company"
            for n in self.record_names(rid):
                for p in T.name_parts(n, comp):
                    self.vocab[p].add(rid)
        self.vocab_by_len = defaultdict(list)
        for p in self.vocab:
            self.vocab_by_len[len(p)].append(p)

    def _vocab_matches(self, part):
        out = set()
        if part in self.vocab:
            out.add(part)
        for g in T._VARIANT_INDEX.get(part, []):
            for w in T.VARIANT_GROUPS[g]:
                if w in self.vocab:
                    out.add(w)
        if len(part) >= 4:
            for L in range(len(part) - 2, len(part) + 3):
                for v in self.vocab_by_len.get(L, ()):
                    if T.part_match(part, v):
                        out.add(v)
            # written together: screened part == two record parts joined
            for i in range(2, len(part) - 1):
                a, b = part[:i], part[i:]
                if a in self.vocab and b in self.vocab:
                    out.add(a)
                    out.add(b)
        return out

    def name_candidates(self, screened_name, company):
        parts = T.name_parts(screened_name, company)
        cands = set()
        for p in parts:
            for v in self._vocab_matches(p):
                cands |= self.vocab[v]
        for i in range(len(parts)):
            for j in range(len(parts)):
                if i != j:
                    for v in self._vocab_matches(parts[i] + parts[j]):
                        cands |= self.vocab[v]
        return cands

    def fits(self, rid, alert, why=None) -> bool:
        """Does a customer record fit what was screened?"""
        c = self.rec(rid)
        comp = norm_type(s(alert.get("entity_type"))) == "Company" or self.rec_type(rid) == "Company"
        sname = s(alert.get("customer_name"))
        if sname:
            if not any(T.names_agree(n, sname, comp) for n in self.record_names(rid)):
                return False
        sdob = T.parse_date(s(alert.get("dob")), dayfirst=True)
        if sdob:
            rdob = self.rec_dob(rid)
            if rdob and not dob_parts_equal(sdob, rdob):
                return False
        sc = T.norm_country(s(alert.get("country")))
        if sc:
            have = {T.norm_country(s(v)) for f in ("residence_country", "nationality") for v in as_list(c.get(f))}
            if sc not in have:
                return False
        scity = s(alert.get("city"))
        if scity:
            rc = T.fold(s(c.get("city"))).strip()
            ra = T.fold(s(c.get("address")))
            ok = False
            for city_f in city_forms(scity):
                if city_f == rc or rc and city_alias(rc) == city_f or re.search(r"\b" + re.escape(city_f) + r"\b", ra):
                    ok = True
                    break
            if not ok:
                return False
        return True

    def resolve(self, alert):
        """Returns (list of person-first record ids, path steps)."""
        path = []
        linked = []
        acc = s(alert.get("account_ref"))
        login = s(alert.get("login_handle")).lower()
        email = s(alert.get("email")).lower()
        if acc:
            rows = self.ds.acc_by_id.get(acc, [])
            linked = list(dict.fromkeys(s(r.get("customer_id")) for r in rows))
            path.append(f"account_ref {acc} → accounts → " + (", ".join(linked) or "no customer"))
        elif login:
            rows = self.ds.acc_by_login.get(login, [])
            linked = list(dict.fromkeys(s(r.get("customer_id")) for r in rows))
            linked += [r for r in self.ds.cust_by_login.get(login, []) if r not in linked]
            path.append(f"login_handle {login} → accounts → " + (", ".join(linked) or "no customer"))
        elif email:
            linked = list(self.ds.cust_by_email.get(email, []))
            path.append(f"email {email} → customers → " + (", ".join(linked) or "no customer"))
        linked = [r for r in linked if r in self.ds.cust_by_id]
        if linked:
            if len(linked) == 1:
                fit = linked
            else:
                fit = [r for r in linked if self.fits(r, alert)]
                path.append(f"{len(linked)} linked records; the screened details fit " + (", ".join(fit) or "none"))
                if not fit:
                    fit = linked
        else:
            comp = norm_type(s(alert.get("entity_type"))) == "Company"
            cands = self.name_candidates(s(alert.get("customer_name")), comp)
            fit = sorted(r for r in cands if self.fits(r, alert))
            path.append("no link: search customers by screened name, date of birth, country and city → "
                        + (", ".join(fit) if fit else "no record fits"))
        # group into people
        people, seen = [], set()
        for r in fit:
            k = self.person_key(r)
            if k in seen:
                continue
            seen.add(k)
            people.append(r)
        for r in people:
            recs = self.person_records.get(self.person_key(r), [r])
            if len(recs) > 1:
                path.append(f"same phone + full date of birth, or same document number → one person: {', '.join(sorted(recs))}")
        if len(people) > 1:
            path.append(f"{len(people)} different people fit; each is decided separately")
        return people, path

    # ---------------------------- hit facts (principle 5) --------------------
    def hit_facts(self, hit) -> HitFacts:
        hid = s(hit.get("hit_id"))
        etype = norm_type(s(hit.get("entity_type")))
        comp = etype == "Company"
        name = s(hit.get("name"))
        names = [name] if name else []
        extra = as_list(hit.get("aliases")) + as_list(hit.get("best_matching_name"))
        for a in extra:
            a = a.get("name") if isinstance(a, dict) else a
            a = T.strip_brackets(s(a)).strip()
            if a and a not in names:
                names.append(a)
        # countries
        countries = set()
        for f in ("countries", "nationality", "citizenship"):
            for v in as_list(hit.get(f)):
                c = T.norm_country(T.strip_brackets(s(v)).split(",")[-1])
                if c:
                    countries.add(c)
        for f in ("addresses", "place_of_birth"):
            for v in as_list(hit.get(f)):
                v = v.get("country") or v.get("address") if isinstance(v, dict) else v
                c = T.norm_country(T.strip_brackets(s(v)).split(",")[-1])
                if c:
                    countries.add(c)
        # categories / listing kind
        cats = [s(c) for c in as_list(hit.get("categories"))]
        prim = s(hit.get("primary_category")) or (cats[0] if cats else "")
        listing = LISTING_PHRASES.get(prim.strip().lower(), OTHER_LISTING)
        notes = s(hit.get("profile_notes"))
        # dobs
        dobs = []
        for v in as_list(hit.get("dobs")):
            d = T.parse_date(s(v), dayfirst=False)
            if d:
                dobs.append((d, "listed", None))
        origin = "listed" if dobs else ""
        if not comp:
            pn = [(d, "profile notes", None) for d in profile_note_dobs(notes)]
            if pn:
                dobs.extend(pn)
                origin = origin or "profile notes"
        search_used = []
        if not dobs and not comp:
            for r in self.ds.search_by_query.get(T.search_key(name), []):
                snip = s(r.get("snippet"))
                if not snippet_about_hit(snip, listing, countries, name):
                    continue
                for d in age_birth_years(snip, fallback=True):
                    dobs.append((d, "search results", s(r.get("result_id"))))
                if s(r.get("result_id")) not in search_used:
                    search_used.append(s(r.get("result_id")))
            if dobs:
                origin = "search results"
        # dated reports
        earliest, line_used = None, ""
        for line in notes.splitlines():
            m = REPORT_LINE.match(line.strip())
            if m:
                d = T.parse_date(m.group(2), dayfirst=False)
                if d and d[1] is not None and d[2] is not None:
                    if earliest is None or d < earliest:
                        earliest, line_used = d, line.strip()
        deceased = T.parse_date(s(hit.get("deceased_date")), dayfirst=False)
        return HitFacts(hit_id=hid, entity_type=etype, name=name, names=names, dobs=dobs, dob_origin=origin,
                        countries=countries, earliest_report=earliest, report_line=line_used,
                        deceased=deceased, listing=listing, search_used=search_used)

    # ---------------------------- decision (principles 6-9) ------------------
    def verified_name_reliable(self, p: Person, comp: bool) -> bool:
        """A name read out of a free-text note is trusted as the legal name only when the note is
        anchored to this person: it shares a name part with their records, or its date of birth
        equals a record's full date of birth. Provider-table names are structured and always trusted."""
        v = p.verified
        if v.kind != "note":
            return True
        vp = T.name_parts(v.name, comp)
        rp = {q for n, _ in p.record_names for q in T.name_parts(n, comp)}
        if any(T.part_match(a, b) for a in vp for b in rp):
            return True
        if v.dob and v.dob[2] is not None:
            for rid in p.records:
                if self.rec_dob(rid) == v.dob:
                    return True
        return False

    def customer_names(self, p: Person, comp: bool):
        """Names to compare, with their source ids. Verified legal name outranks the record."""
        if p.verified and p.verified.name and self.verified_name_reliable(p, comp):
            vp = T.name_parts(p.verified.name, comp)
            if comp or len(vp) >= 2:
                return [(p.verified.name, p.verified.id)], True
        out = []
        for n, rid in p.record_names:
            if comp or len(T.name_parts(n, comp)) >= 2:
                out.append((n, rid))
        return out, False

    def decide_one(self, hit, alert, hf: HitFacts, p: Person) -> dict:
        self._sig = None
        res = self._decide_one(hit, alert, hf, p)
        res["signals"] = self._sig
        return res

    def _decide_one(self, hit, alert, hf: HitFacts, p: Person) -> dict:
        comp_c = p.entity_type == "Company"
        comp_h = hf.entity_type == "Company"
        comp = comp_c or comp_h
        contra = {}   # code -> (evidence ids, sentence)
        screened_at = T.parse_date(s(alert.get("screened_at")), dayfirst=True)
        recs = p.records

        # type
        if p.entity_type and hf.entity_type and p.entity_type != hf.entity_type:
            contra["ENTITY_TYPE_MISMATCH"] = (
                [recs[0]], f"The customer is {'a company' if comp_c else 'a person'} but the hit is "
                           f"{'a company' if comp_h else 'a person'}.")
        # deceased
        if hf.deceased and screened_at and T.date_key_high(hf.deceased) < T.date_key_low(screened_at):
            contra["DECEASED"] = ([recs[0]], f"The hit's profile gives a date of death {T.fmt_date(hf.deceased)}, "
                                             f"before the customer was screened on {T.fmt_date(screened_at)}.")
        # time
        if hf.earliest_report and p.dob:
            if comp_c:
                if T.date_key_low(p.dob) > hf.earliest_report:
                    contra["TEMPORAL_IMPOSSIBILITY"] = (
                        [p.dob_src], f"The customer was incorporated {'on' if p.dob[2] else 'in'} {T.fmt_date(p.dob)} ({p.dob_src}), after the hit's "
                                     f"profile reports activity on {T.fmt_date(hf.earliest_report)}.")
            else:
                age = max_age_at(p.dob, hf.earliest_report)
                if age < 16:
                    contra["TEMPORAL_IMPOSSIBILITY"] = (
                        [p.dob_src], f"The customer was born in {p.dob[0]} ({p.dob_src}), so they were at most "
                                     f"{max(age, 0)} when the hit's profile reports activity on {T.fmt_date(hf.earliest_report)}.")
        # date of birth
        dob_agree = False
        dob_ev = []
        if p.dob and hf.dobs:
            hd = [d for d, _, _ in hf.dobs]
            dob_agree = any(dob_agrees(p.dob, d) for d in hd)
            sr = list(dict.fromkeys(sid for _, _, sid in hf.dobs if sid))
            dob_ev = [p.dob_src] + sr
            if all(dob_contradicts(p.dob, d) for d in hd):
                contra["DOB_MISMATCH"] = (
                    dob_ev, f"The customer's {'incorporation date' if comp_c else 'date of birth'} is {T.fmt_date(p.dob)} "
                            f"({p.dob_src}) but the hit's {describe_hit_dobs(hf)}.")
        # name
        cnames, verified_used = self.customer_names(p, comp)
        name_agree, agreed_with, agreed_cust, name_src = False, None, None, []
        for n, src in cnames:
            for hn in hf.names:
                if T.names_agree(n, hn, comp):
                    name_agree, agreed_with, agreed_cust, name_src = True, hn, n, [src]
                    break
            if name_agree:
                break
        if verified_used and not name_agree and cnames:
            contra["NAME_MISMATCH_VERIFIED"] = (
                [p.verified.id], f"The customer's verified name is {p.verified.name} ({p.verified.id}), which does not "
                                 f"match the hit's name {hf.name}.")
        # location
        ccs = set(p.countries)
        shared = ccs & hf.countries
        loc_agree = bool(shared)
        if ccs and hf.countries and not shared:
            ev = []
            for c in sorted(ccs):
                for src in p.countries[c]:
                    if src not in ev:
                        ev.append(src)
            sent = (f"The customer is linked only to {', '.join(sorted(ccs))} but the hit is linked only to "
                    f"{', '.join(sorted(hf.countries))}.")
            if name_agree and dob_agree and not comp:
                pass  # a country difference does not clear a hit whose name and DOB agree -> REVIEW
            else:
                contra["LOCATION_MISMATCH"] = (ev, sent)

        # per-check signals for the analyst UI
        hit_dobs_txt = sorted({T.fmt_date(d) for d, _, _ in hf.dobs})
        sig = {
            "type": {"state": "contradict" if "ENTITY_TYPE_MISMATCH" in contra else "agree" if p.entity_type and hf.entity_type else "unknown",
                     "customer": p.entity_type, "hit": hf.entity_type},
            "name": {"state": "contradict" if "NAME_MISMATCH_VERIFIED" in contra else "agree" if name_agree else "unknown",
                     "customer": [n for n, _ in cnames][:3], "verified": verified_used, "hit": hf.names[:6],
                     "matched": agreed_with, "src": name_src or ([p.verified.id] if verified_used else [])},
            "dob": {"state": "contradict" if "DOB_MISMATCH" in contra else "agree" if dob_agree else "unknown",
                    "customer": T.fmt_date(p.dob) if p.dob else None, "customer_src": p.dob_src,
                    "hit": hit_dobs_txt, "hit_origin": hf.dob_origin,
                    "hit_src": list(dict.fromkeys(sid for _, _, sid in hf.dobs if sid))},
            "location": {"state": "contradict" if "LOCATION_MISMATCH" in contra else "agree" if loc_agree
                         else ("differs" if ccs and hf.countries else "unknown"),
                         "customer": {c: v for c, v in sorted(p.countries.items())}, "hit": sorted(hf.countries),
                         "shared": sorted(shared)},
            "time": {"state": "contradict" if "TEMPORAL_IMPOSSIBILITY" in contra else ("clear" if hf.earliest_report else "unknown"),
                     "earliest_report": T.fmt_date(hf.earliest_report) if hf.earliest_report else None,
                     "line": hf.report_line[:300]},
            "deceased": {"state": "contradict" if "DECEASED" in contra else ("clear" if hf.deceased else "unknown"),
                         "date": T.fmt_date(hf.deceased) if hf.deceased else None},
        }
        self._sig = sig

        if contra:
            codes = [c for c in CODE_PRIORITY if c in contra]
            ev = []
            for c in codes:
                for x in contra[c][0]:
                    if x and x not in ev:
                        ev.append(x)
            sents = [contra[c][1] for c in codes[:3]]
            if name_agree and len(sents) < 3 and codes[0] != "NAME_MISMATCH_VERIFIED":
                sents.append(f"The names agree ({agreed_cust} and {agreed_with}), but a shared name alone "
                             f"does not make them the same {'company' if comp else 'person'}.")
            sents.append(CLEAR_TAIL[codes[0]].format(hit=hit_label(hf), kind="company" if comp_h else "person"))
            return dict(decision="DIFFERENT_ENTITY", reason_code=codes[0], all_codes=codes, evidence=ev,
                        explanation=" ".join(sents), sentences=sents)

        loc_ev = []
        for c in sorted(shared):
            for src in p.countries[c]:
                if src not in loc_ev:
                    loc_ev.append(src)
        name_txt = (f"The customer's {'verified legal name' if verified_used else 'name'} {agreed_cust} "
                    f"({name_src[0]}) agrees with the hit's name {agreed_with}") if name_agree else ""
        dob_txt = (f"the {'incorporation date' if comp_c else 'date of birth'} {T.fmt_date(p.dob)} ({p.dob_src}) "
                   f"agrees with the hit's {' or '.join(hit_dobs_txt)}") if dob_agree else ""
        loc_txt = f"both are linked to {', '.join(sorted(shared))}" if loc_agree else ""

        def ev_union(*lists):
            out = []
            for L in lists:
                for x in L:
                    if x and x not in out:
                        out.append(x)
            return out

        if not comp and name_agree and dob_agree:
            code = "NAME_DOB_LOCATION_MATCH" if loc_agree else "NAME_DOB_MATCH"
            sents = [name_txt + ".", cap(dob_txt) + (f", and {loc_txt}." if loc_agree else ".")]
            sents.append(f"Nothing in the customer's records contradicts the hit, so {hit_label(hf)} is the customer.")
            return dict(decision="SAME_ENTITY", reason_code=code,
                        all_codes=[code] + (["NAME_DOB_MATCH"] if loc_agree else []),
                        evidence=ev_union(loc_ev, dob_ev) or ev_union(name_src),
                        explanation=" ".join(sents), sentences=sents)
        if comp and comp_c and comp_h and name_agree and loc_agree:
            sents = [name_txt + f", and {loc_txt}.",
                     f"Nothing in the customer's records contradicts the hit, so {hit_label(hf)} is the customer."]
            return dict(decision="SAME_ENTITY", reason_code="NAME_LOCATION_MATCH", all_codes=["NAME_LOCATION_MATCH"],
                        evidence=ev_union(loc_ev) or ev_union(name_src),
                        explanation=" ".join(sents), sentences=sents)

        # REVIEW: say what agrees, what is missing, and why that leaves it open.
        sents = []
        agrees = [x for x in (name_txt, dob_txt, loc_txt) if x]
        if agrees:
            sents.append(cap(", and ".join(agrees)) + ".")
        if not comp and name_agree and dob_agree and not loc_agree:
            sents.append(f"But the customer is linked only to {', '.join(sorted(ccs))} and the hit only to "
                         f"{', '.join(sorted(hf.countries))}, and a country difference does not clear a hit whose "
                         f"name and date of birth agree.")
            sents.append(f"The evidence conflicts, so {hit_label(hf)} goes to an analyst.")
        else:
            gaps = []
            if not name_agree:
                if not cnames:
                    gaps.append("the customer has no name with two real parts to compare")
                else:
                    gaps.append(f"the customer's name {cnames[0][0]} does not clearly agree with the hit's name "
                                f"{hf.name}, and without an approved identity check that cannot clear it")
            if not comp and not dob_agree:
                if not p.dob and not hf.dobs:
                    gaps.append("neither side gives a date of birth")
                elif not p.dob:
                    gaps.append("the customer's records give no date of birth")
                elif not hf.dobs:
                    gaps.append("the hit gives no date of birth in its listing, profile notes or matching search results")
                else:
                    gaps.append(f"the customer's date of birth {T.fmt_date(p.dob)} ({p.dob_src}) neither agrees with "
                                f"nor contradicts the hit's {' or '.join(hit_dobs_txt)}")
            if comp and not loc_agree:
                gaps.append("the customer and the hit share no country" if ccs and hf.countries
                            else "the country cannot be compared")
            sents.append(cap("; ".join(gaps or ["the evidence is incomplete"])) + ".")
            sents.append(f"Nothing contradicts the hit and too little agrees to confirm it, so {hit_label(hf)} "
                         f"goes to an analyst.")
        return dict(decision="REVIEW", reason_code="INSUFFICIENT_DATA", all_codes=["INSUFFICIENT_DATA"],
                    evidence=ev_union(loc_ev, dob_ev if dob_agree else []) or ev_union(name_src),
                    explanation=" ".join(sents), sentences=sents)

    def decide_alert(self, alert) -> list[dict]:
        people, path = self.resolve(alert)
        out = []
        for hid in as_list(alert.get("hit_ids")):
            hid = s(hid)
            hit = self.ds.hit_by_id.get(hid)
            if hit is None:
                continue
            hf = self.hit_facts(hit)
            if not people:
                out.append(dict(hit_id=hid, alert_id=s(alert.get("alert_id")), decision="REVIEW",
                                reason_code="INSUFFICIENT_DATA", customer_record_id=None, evidence=[],
                                explanation=(f"No customer record in the system of record fits the alert for "
                                             f"{s(alert.get('customer_name')) or 'the screened customer'}, so there is "
                                             f"nothing to compare the hit with. Without the customer's details "
                                             f"{hit_label(hf)} can be neither cleared nor confirmed."),
                                path=path, persons=[], hit_facts=hf))
                continue
            per = []
            for r in people:
                p = self.person(r)
                res = self.decide_one(hit, alert, hf, p)
                res["person"] = p
                per.append(res)
            if len(per) == 1:
                r0 = per[0]
                rec = dict(decision=r0["decision"], reason_code=r0["reason_code"], all_codes=r0["all_codes"],
                           customer_record_id=r0["person"].primary, evidence=r0["evidence"],
                           explanation=r0["explanation"])
            else:
                decisions = {x["decision"] for x in per}
                ev = []
                for x in per:
                    for e in x["person"].records + x["evidence"]:
                        if e not in ev:
                            ev.append(e)
                if len(decisions) == 1:
                    rec = dict(decision=per[0]["decision"], reason_code=per[0]["reason_code"],
                               all_codes=per[0]["all_codes"], customer_record_id="AMBIGUOUS", evidence=ev,
                               explanation=" ".join(cap_sentences(
                                   [f"{len(per)} different people fit the alert "
                                    f"({', '.join(x['person'].primary for x in per)}) and all lead to the same decision."]
                                   + per[0]["sentences"], 4)))
                else:
                    rec = dict(decision="REVIEW", reason_code="AMBIGUOUS_CUSTOMER_RECORD",
                               all_codes=["AMBIGUOUS_CUSTOMER_RECORD"], customer_record_id="AMBIGUOUS", evidence=ev,
                               explanation=(f"{len(per)} different people fit the alert and they lead to different "
                                            f"decisions ({', '.join(x['person'].primary + ': ' + x['decision'] for x in per)}). "
                                            f"The bank's records cannot say which of them was screened, so "
                                            f"{hit_label(hf)} goes to an analyst."))
            rec["explanation"] = re.sub(r"(?<!\.)\.\.(?!\.)", ".", rec["explanation"])
            rec.update(hit_id=hid, alert_id=s(alert.get("alert_id")), path=path, persons=per, hit_facts=hf)
            out.append(rec)
        return out

    def run(self):
        results = []
        for a in self.ds.alerts:
            results.extend(self.decide_alert(a))
        return results


# ----------------------------------------------------------------------------
# Free-text extractors
# ----------------------------------------------------------------------------
REPORT_LINE = re.compile(r"^According to (.+?); ((?:January|February|March|April|May|June|July|August|September|"
                         r"October|November|December) \d{1,2}, \d{4}):")

# explicit age phrasings (safe in free-form profile text)
_AGE_PATTERNS = [
    re.compile(r"\baged\s+(\d{1,3})\b", re.I),
    re.compile(r"\b(\d{1,3})[\s\-]+years?[\s\-]+old\b", re.I),
    re.compile(r"\b(\d{1,3})\s+years?\s+of\s+age\b", re.I),
    re.compile(r"\bage\s+of\s+(\d{1,3})\b", re.I),
    re.compile(r"\bage\s+of\s+[^.;\d]{1,80}?\s+(?:was|is)\s+(\d{1,3})\b", re.I),
    re.compile(r"\bAge:\s*(\d{1,3})\b"),
    re.compile(r"\bat\s+(?:the\s+)?age\s+(\d{1,3})\b", re.I),
    re.compile(r"\b(?:he|she|they|who|the subject|the individual|the person)\s+(?:was|were|is|turned)\s+(?:then\s+|aged\s+)?(\d{1,3})\b"
               r"(?!\s*(?:%|percent|times|people|others|kg|grams|counts?|cases|months|days|years? (?:in|of|for)))", re.I),
    re.compile(r"\b(?:was|turned)\s+(?:then\s+)?(\d{1,3})\s*(?=[.,;)]|$)", re.I),
    re.compile(r"\breached\s+(\d{1,3})\b", re.I),
    re.compile(r"\bwas\s+(\d{1,3})\s+(?=when|at the time|upon|as of|during|while|by the time|at that time)", re.I),
]
_UNIT_AFTER = re.compile(r"\s*(?:%|percent|per cent|times|people|persons|others|individuals|suspects|men|women|"
                         r"kg|kgs|kilograms?|grams?|g\b|km|miles|counts?|cases|charges|months|days|weeks|hours|"
                         r"years?\s+(?:in|of|for|prison|jail)|million|billion|thousand|crore|lakh|usd|eur|gbp|inr|ngn|"
                         r"bdt|pkr|\$)", re.I)
# templated search snippets also write ages as ", 35," or "at 30."
_SNIPPET_PATTERNS = _AGE_PATTERNS + [
    re.compile(r"(?:^|[,(])\s*(\d{1,3})\s*(?=[,).])"),
    re.compile(r"\bat\s+(\d{1,3})\s*(?=[.,;]|$)", re.I),
]
AGE_CUE = re.compile(r"aged\s+\d|\d[\s\-]+years?[\s\-]+old|years? of age|age of|\bage\s+\d|Age:\s*\d|"
                     r"\b(?:he|she|they|who|the subject|the individual|the person) (?:was|were|is|turned) (?:then )?\d|"
                     r"\b(?:was|turned) (?:then )?\d{1,3}\s*(?:[.,;)]|$)|reached \d", re.I)


def _first_age(sent, fallback=False):
    for rx in (_SNIPPET_PATTERNS if fallback else _AGE_PATTERNS):
        m = rx.search(sent)
        if m:
            n = int(m.group(1))
            if 0 < n < 120:
                return n, m.span(1)
    if fallback:
        # templated snippets: the one small standalone number outside any date
        spans = [(a, b) for a, b, _ in T.find_dates(sent, dayfirst=False)]
        nums = [m for m in re.finditer(r"(?<![\d/\-.:])(\d{1,3})(?![\d/\-:]|\.\d)", sent)
                if not any(a <= m.start() < b for a, b in spans) and 0 < int(m.group(1)) < 120]
        if len(nums) == 1:
            return int(nums[0].group(1)), nums[0].span(1)
    return None, None


def _ref_date(sent, avoid=None):
    """The date an age refers to: prefer 'as of <date>', else the first date in the sentence."""
    m = re.search(r"as of ([^:;\n]+)", sent)
    if m:
        ds = T.find_dates(m.group(1), dayfirst=False)
        if ds:
            return ds[0][2]
    ds = T.find_dates(sent, dayfirst=False)
    for s_, e_, d in ds:
        if avoid and not (e_ <= avoid[0] or s_ >= avoid[1]):
            continue
        return d
    return None


def age_birth_years(sent: str, fallback=False):
    """An age at a date gives two possible birth years."""
    n, span = _first_age(sent, fallback)
    if n is None:
        return []
    ref = _ref_date(sent, avoid=span)
    if not ref:
        return []
    y = ref[0]
    return [(y - n, None, None), (y - n - 1, None, None)]


_BORN = re.compile(r"\bborn (?:on |in )?(.+?)(?:[.;]\s|[.;]?$| in [A-Z])")
_DOB_LABEL = re.compile(r"\b(?:DOB|D\.O\.B\.|Date of Birth|Date\(s\) of Birth(?: Used)?|Birth ?date)\s*[:\-]\s*([^\n;]+)", re.I)


def profile_note_dobs(notes: str):
    """Birth dates stated in the first paragraph of a hit's profile notes."""
    if not notes:
        return []
    first = re.split(r"\n\s*\n", notes.strip(), maxsplit=1)[0]
    out = []
    for m in _DOB_LABEL.finditer(first):
        d = T.parse_date(m.group(1), dayfirst=False)
        if d:
            out.append(d)
    for m in _BORN.finditer(first):
        ds = T.find_dates(m.group(1), dayfirst=False)
        if ds:
            out.append(ds[0][2])
    if not out:
        # ages at a date, sentence by sentence (a sentence may be a line in a record block)
        has_age_line = re.search(r"\bAge:\s*\d", first)
        if has_age_line:
            out.extend(age_birth_years(first))
        else:
            for sent in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n", first):
                if sent.strip().startswith("According to"):
                    continue  # dated reports are activity, not ages
                if AGE_CUE.search(sent):
                    ys = age_birth_years(sent)
                    if ys:
                        out.extend(ys)
                        continue
                ys = generic_age_sentence(sent)
                if ys:
                    out.extend(ys)
    uniq = []
    for d in out:
        if d not in uniq:
            uniq.append(d)
    return uniq


def generic_age_sentence(sent: str):
    """Fallback for unseen phrasings: a short sentence with exactly one month-year date and exactly
    one small bare number (not a quantity) is an age at that date."""
    if len(sent) > 220 or not re.search(r"\bwas\b|\bis\b|\baged?\b|\bold\b|\bturned\b|\breached\b", sent, re.I):
        return []
    all_dates = T.find_dates(sent, dayfirst=False)
    dates = [d for d in all_dates if d[2][1] is not None and d[2][2] is None]  # "in January 2025"
    if len(dates) != 1 or len(all_dates) != 1:
        return []
    spans = [(a, b) for a, b, _ in all_dates]
    nums = []
    for m in re.finditer(r"(?<![\d/\-.:,$£€§])(\d{1,3})(?![\d/\-:]|\.\d|,\d)", sent):
        if any(a <= m.start() < b for a, b in spans):
            continue
        if _UNIT_AFTER.match(sent[m.end():]) or re.match(r"\s*[A-Z]\.", sent[m.end():]):
            continue
        before = sent[:m.start()].rstrip()
        if not (before.endswith(",") or re.search(r"\b(?:was|then|at|aged|age|is|turned|reached|of)$", before, re.I)):
            continue
        n = int(m.group(1))
        if 0 < n < 120:
            nums.append(n)
    if len(nums) != 1:
        return []
    y = dates[0][2][0]
    return [(y - nums[0], None, None), (y - nums[0] - 1, None, None)]


def snippet_about_hit(snip: str, listing: str, hit_countries: set, name: str) -> bool:
    """A search result is about the hit only if it describes the same kind of listing in a
    country tied to the hit."""
    if listing not in snip:
        return False
    if not hit_countries:
        return False
    # don't let the person's own name be read as a country (e.g. 'Jordan')
    name_tokens = set(T.fold(name).replace(",", " ").split())
    cleaned = " ".join(w if T.fold(w.strip(",.()")) not in name_tokens else "_" for w in snip.split())
    found = set(T.find_countries(cleaned))
    return bool(found & hit_countries)


_NOTE_STOP = {
    "sumsub", "onfido", "veriff", "persona", "jumio", "trulioo", "idnow", "yoti", "mitek", "socure", "experian",
    "equifax", "lexisnexis", "shufti", "complyadvantage", "companies", "registry", "id", "dob", "kyc", "customer",
    "client", "user", "verified", "verification", "result", "per", "validation", "on", "identity", "the", "a", "an",
    "passport", "national", "driving", "licence", "license", "document", "check", "completed", "confirmed",
    "approved", "date", "birth", "name", "holder", "as", "of", "in", "via", "using", "with", "for", "his", "her",
    "their", "this", "that", "record", "records", "account", "team", "onboarding", "note", "notes", "issued",
}


def parse_kyc_note(txt: str, created):
    """Extract (name, dob, document country, check date) from an onboarding/KYC note."""
    dates = T.find_dates(txt, dayfirst=True, years=False)
    check_date, dob = None, None
    for s_, e_, d in dates:
        if created and d == created and check_date is None:
            check_date = d
            continue
        if dob is None:
            dob = d
    if dob is None and len(dates) >= 2:
        dob = dates[0][2]
    if dob is None:  # year-only birth dates: "born 1966", "DOB 1960", "date of birth of 1974"
        m = re.search(r"\b(?:DOB|born|birth(?:\s*date)?|date of birth)\b[^0-9]{0,25}?\b(1[89]\d{2}|20\d{2})\b", txt, re.I)
        if m:
            dob = (int(m.group(1)), None, None)
    # name: the longest run of upper-case words
    toks = re.findall(r"[^\s,;:()]+", txt)
    best, cur = [], []
    for t in toks:
        tt = re.sub(r"['’]s$", "", t).strip(".'’")
        if tt and UPPER_TOKEN.match(tt) and tt not in NOT_NAME_UPPER and (len(tt) > 1 or cur):
            cur.append(tt)
        else:
            if len(cur) > len(best):
                best = cur
            cur = []
    if len(cur) > len(best):
        best = cur
    name = " ".join(best) if len(best) >= 2 else ""
    if not name:
        # Title-case fallback: the longest run of capitalised words that is not a provider,
        # month, country or document word ("... held by Nils Martin (1965-05-19) ...")
        runs, cur = [], []
        for t in re.findall(r"[^\s,;:()]+", txt):
            tt = t.strip(".'’")
            ok = (tt[:1].isupper() and tt[1:].replace("-", "").replace("'", "").isalpha() and tt.lower() not in _NOTE_STOP
                  and not T.find_countries(tt) and tt.lower().rstrip(".") not in T.MONTHS)
            if ok:
                cur.append(tt)
            else:
                if cur:
                    runs.append(cur)
                cur = []
        if cur:
            runs.append(cur)
        # a run that is itself a country ("United States") is a document country, not a name
        runs = [r for r in runs if len(r) >= 2 and not T.is_country_name(" ".join(r))]
        if runs:
            name = " ".join(max(runs, key=len))
        elif best:
            name = " ".join(best)
    cs = T.find_countries(txt)
    country = cs[0] if cs else None
    if not name and not dob:
        return None
    return name, dob, country, check_date


def describe_hit_dobs(hf: HitFacts) -> str:
    ds = sorted({T.fmt_date(d) for d, _, _ in hf.dobs})
    if hf.dob_origin == "listed" and len(ds) == 1:
        return f"listed date of birth is {ds[0]}"
    src = {"listed": "listed dates of birth", "profile notes": "profile notes", "search results": "search results"}
    years = sorted({d[0] for d, _, _ in hf.dobs})
    if hf.dob_origin in ("profile notes", "search results") and all(d[1] is None for d, _, _ in hf.dobs):
        return f"{src[hf.dob_origin]} put its birth year at {' or '.join(map(str, years))}"
    return f"{src.get(hf.dob_origin, 'profile')} give {' or '.join(ds)}"
